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
        self.ghost_window_bytes = 0
        self.ghost_main_bytes = 0
        self.window_target = self.capacity // 2
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096
        self.serial = 0

    def _drop_ghost(self, key):
        value = self.ghost_window.pop(key, None)
        if value is not None:
            self.ghost_window_bytes -= value[0]
            return 1
        value = self.ghost_main.pop(key, None)
        if value is not None:
            self.ghost_main_bytes -= value[0]
            return 2
        return 0

    def _remember_ghost(self, key, size, kind):
        self._drop_ghost(key)
        self.serial += 1
        value = (size, self.serial)
        if kind == 1:
            self.ghost_window[key] = value
            self.ghost_window_bytes += size
        else:
            self.ghost_main[key] = value
            self.ghost_main_bytes += size
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_window_bytes + self.ghost_main_bytes > self.ghost_limit or
               len(self.ghost_window) + len(self.ghost_main) > self.ghost_count_limit):
            choices = []
            if self.ghost_window:
                choices.append((next(iter(self.ghost_window.items()))[1][1], 1))
            if self.ghost_main:
                choices.append((next(iter(self.ghost_main.items()))[1][1], 2))
            if not choices:
                return
            kind = min(choices, key=lambda item: item[0])[1]
            if kind == 1:
                _, value = self.ghost_window.popitem(last=False)
                self.ghost_window_bytes -= value[0]
            else:
                _, value = self.ghost_main.popitem(last=False)
                self.ghost_main_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        if kind == 1:
            a = self.ghost_window_bytes
            b = self.ghost_main_bytes
            step = self.capacity if a == 0 else max(1, min(self.capacity, b // a or 1))
            self.window_target = min(self.capacity, self.window_target + step)
        else:
            a = self.ghost_window_bytes
            b = self.ghost_main_bytes
            step = self.capacity if b == 0 else max(1, min(self.capacity, a // b or 1))
            self.window_target = max(0, self.window_target - step)

    def _evict_one(self, prefer_window):
        if prefer_window and self.window:
            key, size = self.window.popitem(last=False)
            self.window_bytes -= size
            self._remember_ghost(key, size, 1)
            return key
        if self.main:
            key, size = self.main.popitem(last=False)
            self.main_bytes -= size
            self._remember_ghost(key, size, 2)
            return key
        if self.window:
            key, size = self.window.popitem(last=False)
            self.window_bytes -= size
            self._remember_ghost(key, size, 1)
            return key
        return None

    def _make_room(self, incoming, incoming_kind):
        evicted = []
        while self.window_bytes + self.main_bytes + incoming > self.capacity:
            prefer_window = bool(self.window) and (
                self.window_bytes > self.window_target or
                (incoming_kind == 2 and self.window_bytes == self.window_target)
            )
            victim = self._evict_one(prefer_window)
            if victim is None:
                break
            evicted.append(victim)
        return evicted

    def access(self, key, size, now):
        key = int(key)
        size = max(0, int(size))

        if key in self.window:
            old = self.window.pop(key)
            self.window_bytes -= old
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            self.main[key] = size
            self.main_bytes += size
            return evicted

        if key in self.main:
            old = self.main.pop(key)
            self.main_bytes -= old
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            self.main[key] = size
            self.main_bytes += size
            return evicted

        ghost_kind = 1 if key in self.ghost_window else 2 if key in self.ghost_main else 0
        if size <= 0 or size > self.capacity:
            return []

        if ghost_kind:
            self._adjust_target(ghost_kind)
            self._drop_ghost(key)

        evicted = self._make_room(size, ghost_kind)
        if ghost_kind:
            self.main[key] = size
            self.main_bytes += size
        else:
            self.window[key] = size
            self.window_bytes += size
        return evicted
