from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        self.capacity = max(0, int(capacity_bytes))
        self.window = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_window = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.window_bytes = 0
        self.protected_bytes = 0
        self.used = 0
        self.target = self.capacity // 2
        self.ghost_bytes = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096
        self.clock = 0

    def _forget_ghost(self, key):
        for table in (self.ghost_window, self.ghost_protected):
            value = table.pop(key, None)
            if value is not None:
                self.ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, kind):
        self._forget_ghost(key)
        self.clock += 1
        value = (max(1, int(size)), self.clock)
        if kind == 1:
            self.ghost_window[key] = value
        else:
            self.ghost_protected[key] = value
        self.ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_window) + len(self.ghost_protected) > self.ghost_count_limit):
            source = None
            oldest = None
            for table in (self.ghost_window, self.ghost_protected):
                if table:
                    value = next(iter(table.values()))
                    if oldest is None or value[1] < oldest[1]:
                        source = table
                        oldest = value
            if source is None:
                break
            _, value = source.popitem(last=False)
            self.ghost_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        window_ghost_bytes = sum(value[0] for value in self.ghost_window.values())
        protected_ghost_bytes = sum(value[0] for value in self.ghost_protected.values())
        if kind == 1:
            delta = (self.capacity if window_ghost_bytes == 0 else
                     max(1, min(self.capacity,
                                protected_ghost_bytes // window_ghost_bytes or 1)))
            self.target = min(self.capacity, self.target + delta)
        else:
            delta = (self.capacity if protected_ghost_bytes == 0 else
                     max(1, min(self.capacity,
                                window_ghost_bytes // protected_ghost_bytes or 1)))
            self.target = max(0, self.target - delta)

    def _evict_one(self, ghost_kind):
        prefer_window = bool(self.window and self.window_bytes >= self.target)
        if ghost_kind == 2 and self.window and self.window_bytes == self.target:
            prefer_window = False
        if prefer_window:
            key, size = self.window.popitem(last=False)
            self.window_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 1)
            return key
        if self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
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
            key = self._evict_one(ghost_kind)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def _remove_resident(self, key):
        size = self.window.pop(key, None)
        if size is not None:
            self.window_bytes -= size
            self.used -= size
            return size, 1
        size = self.protected.pop(key, None)
        if size is not None:
            self.protected_bytes -= size
            self.used -= size
            return size, 2
        return None

    def access(self, key, size, now):
        del now
        key = int(key)
        size = max(0, int(size))

        resident = self._remove_resident(key)
        if resident is not None:
            old_size, old_kind = resident
            if size <= 0 or size > self.capacity:
                self._remember_ghost(key, old_size, old_kind)
                return [key]
            evicted = self._make_room(size, 0)
            if self.used + size > self.capacity:
                self._remember_ghost(key, size, old_kind)
                return evicted + [key]
            self._forget_ghost(key)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            return evicted

        if size <= 0 or size > self.capacity:
            return []

        if key in self.ghost_window:
            ghost_kind = 1
        elif key in self.ghost_protected:
            ghost_kind = 2
        else:
            ghost_kind = 0

        if ghost_kind:
            self._adjust_target(ghost_kind)
            self._forget_ghost(key)

        evicted = self._make_room(size, ghost_kind)
        if self.used + size > self.capacity:
            return evicted

        if ghost_kind:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.window[key] = size
            self.window_bytes += size
        self.used += size
        return evicted
