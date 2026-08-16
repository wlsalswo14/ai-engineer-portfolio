from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        self.capacity = max(0, int(capacity_bytes))
        self.window = OrderedDict()
        self.main = OrderedDict()
        self.ghost_window = OrderedDict()
        self.ghost_main = OrderedDict()
        self.window_bytes = 0
        self.main_bytes = 0
        self.used = 0
        self.target = self.capacity // 2
        self.ghost_window_bytes = 0
        self.ghost_main_bytes = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096
        self.serial = 0

    def _drop_ghost(self, key):
        value = self.ghost_window.pop(key, None)
        if value is not None:
            self.ghost_window_bytes -= value[0]
        value = self.ghost_main.pop(key, None)
        if value is not None:
            self.ghost_main_bytes -= value[0]

    def _remember_ghost(self, key, size, kind):
        self._drop_ghost(key)
        self.serial += 1
        value = (max(1, int(size)), self.serial)
        if kind == 1:
            self.ghost_window[key] = value
            self.ghost_window_bytes += value[0]
        else:
            self.ghost_main[key] = value
            self.ghost_main_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_window_bytes + self.ghost_main_bytes > self.ghost_limit or
               len(self.ghost_window) + len(self.ghost_main) > self.ghost_count_limit):
            source = None
            key = None
            stamp = None
            for ghosts in (self.ghost_window, self.ghost_main):
                if ghosts:
                    candidate = next(iter(ghosts))
                    value = ghosts[candidate]
                    if stamp is None or value[1] < stamp:
                        source = ghosts
                        key = candidate
                        stamp = value[1]
            value = source.pop(key)
            if source is self.ghost_window:
                self.ghost_window_bytes -= value[0]
            else:
                self.ghost_main_bytes -= value[0]

    def _adjust_target(self, kind, size):
        if self.capacity <= 0:
            return
        if kind == 1:
            ratio = self.ghost_main_bytes // self.ghost_window_bytes if self.ghost_window_bytes else 0
            delta = max(1, int(size), ratio)
            self.target = min(self.capacity, self.target + min(self.capacity, delta))
        else:
            ratio = self.ghost_window_bytes // self.ghost_main_bytes if self.ghost_main_bytes else 0
            delta = max(1, int(size), ratio)
            self.target = max(0, self.target - min(self.capacity, delta))

    def _remove_resident(self, key):
        value = self.window.pop(key, None)
        if value is not None:
            self.window_bytes -= value
            self.used -= value
            return value
        value = self.main.pop(key, None)
        if value is not None:
            self.main_bytes -= value
            self.used -= value
            return value
        return None

    def _evict_one(self, prefer_window):
        if prefer_window and self.window:
            key, size = self.window.popitem(last=False)
            self.window_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 1)
            return key
        if self.main:
            key, size = self.main.popitem(last=False)
            self.main_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 2)
            return key
        if self.window:
            key, size = self.window.popitem(last=False)
            self.window_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 1)
            return key
        return None

    def _make_room(self, incoming, ghost_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            prefer_window = self.window_bytes > self.target
            if ghost_kind == 1 and self.window_bytes >= self.target:
                prefer_window = True
            elif ghost_kind == 2 and self.window_bytes == self.target:
                prefer_window = False
            key = self._evict_one(prefer_window)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key, size, now):
        key = int(key)
        size = max(0, int(size))
        _ = now

        if key in self.window or key in self.main:
            self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            if self.used + size > self.capacity:
                return evicted + [key]
            self._drop_ghost(key)
            self.main[key] = size
            self.main_bytes += size
            self.used += size
            return evicted

        ghost_kind = 1 if key in self.ghost_window else 2 if key in self.ghost_main else 0
        if size <= 0 or size > self.capacity:
            return []

        if ghost_kind:
            self._adjust_target(ghost_kind, size)
            self._drop_ghost(key)

        evicted = self._make_room(size, ghost_kind)
        if self.used + size > self.capacity:
            return evicted

        if ghost_kind:
            self.main[key] = size
            self.main_bytes += size
        else:
            self.window[key] = size
            self.window_bytes += size
        self.used += size
        return evicted
