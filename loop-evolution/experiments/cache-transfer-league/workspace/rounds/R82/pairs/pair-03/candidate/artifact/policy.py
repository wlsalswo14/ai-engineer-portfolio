from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        self.capacity = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.recent_bytes = 0
        self.protected_bytes = 0
        self.ghost_recent_bytes = 0
        self.ghost_protected_bytes = 0
        self.used = 0
        self.recent_target = self.capacity // 2
        self._ghost_serial = 0
        self._ghost_bytes = 0
        self._ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self._ghost_count_limit = 4096

    def _drop_ghost(self, key):
        value = self.ghost_recent.pop(key, None)
        if value is not None:
            self.ghost_recent_bytes -= value[0]
            self._ghost_bytes -= value[0]
        value = self.ghost_protected.pop(key, None)
        if value is not None:
            self.ghost_protected_bytes -= value[0]
            self._ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, kind):
        self._drop_ghost(key)
        self._ghost_serial += 1
        value = (max(1, int(size)), self._ghost_serial)
        if kind == 1:
            self.ghost_recent[key] = value
            self.ghost_recent_bytes += value[0]
        else:
            self.ghost_protected[key] = value
            self.ghost_protected_bytes += value[0]
        self._ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self._ghost_bytes > self._ghost_limit or
               len(self.ghost_recent) + len(self.ghost_protected) > self._ghost_count_limit):
            recent_key = next(iter(self.ghost_recent), None)
            protected_key = next(iter(self.ghost_protected), None)
            if recent_key is None:
                queue = self.ghost_protected
            elif protected_key is None:
                queue = self.ghost_recent
            elif self.ghost_recent[recent_key][1] <= self.ghost_protected[protected_key][1]:
                queue = self.ghost_recent
            else:
                queue = self.ghost_protected
            _, value = queue.popitem(last=False)
            if queue is self.ghost_recent:
                self.ghost_recent_bytes -= value[0]
            else:
                self.ghost_protected_bytes -= value[0]
            self._ghost_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        if kind == 1:
            if self.ghost_recent_bytes == 0:
                delta = self.capacity
            else:
                delta = max(1, min(self.capacity,
                                    self.ghost_protected_bytes // self.ghost_recent_bytes or 1))
            self.recent_target = min(self.capacity, self.recent_target + delta)
        else:
            if self.ghost_protected_bytes == 0:
                delta = self.capacity
            else:
                delta = max(1, min(self.capacity,
                                    self.ghost_recent_bytes // self.ghost_protected_bytes or 1))
            self.recent_target = max(0, self.recent_target - delta)

    def _evict_one(self, prefer_recent):
        if prefer_recent and self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 1)
            return key
        if self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 2)
            return key
        if self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 1)
            return key
        return None

    def _make_room(self, incoming, ghost_kind=0):
        evicted = []
        while self.used + incoming > self.capacity:
            prefer_recent = self.recent_bytes > self.recent_target
            if ghost_kind == 1 and self.recent_bytes == self.recent_target and self.recent:
                prefer_recent = True
            key = self._evict_one(prefer_recent)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key, size, now):
        key = int(key)
        size = max(0, int(size))

        if key in self.recent:
            old_size = self.recent.pop(key)
            self.recent_bytes -= old_size
            self.used -= old_size
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            return evicted

        if key in self.protected:
            old_size = self.protected.pop(key)
            self.protected_bytes -= old_size
            self.used -= old_size
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            return evicted

        ghost_kind = 1 if key in self.ghost_recent else 2 if key in self.ghost_protected else 0
        if size <= 0 or size > self.capacity:
            return []

        if ghost_kind:
            self._adjust_target(ghost_kind)
            self._drop_ghost(key)

        evicted = self._make_room(size, ghost_kind)
        if ghost_kind == 2:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.recent[key] = size
            self.recent_bytes += size
        self.used += size
        return evicted
