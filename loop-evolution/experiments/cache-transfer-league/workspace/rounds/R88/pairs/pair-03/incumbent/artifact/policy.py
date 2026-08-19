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
        self.used = 0
        self.target = self.capacity // 2
        self.ghost_recent_bytes = 0
        self.ghost_protected_bytes = 0
        self.ghost_bytes = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096
        self.clock = 0

    def _drop_ghost(self, key):
        value = self.ghost_recent.pop(key, None)
        if value is not None:
            self.ghost_recent_bytes -= value[0]
            self.ghost_bytes -= value[0]
        value = self.ghost_protected.pop(key, None)
        if value is not None:
            self.ghost_protected_bytes -= value[0]
            self.ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, protected):
        self._drop_ghost(key)
        if size <= 0:
            return
        self.clock += 1
        value = (size, self.clock)
        if protected:
            self.ghost_protected[key] = value
            self.ghost_protected_bytes += size
        else:
            self.ghost_recent[key] = value
            self.ghost_recent_bytes += size
        self.ghost_bytes += size
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_recent) + len(self.ghost_protected) > self.ghost_count_limit):
            chosen = None
            bucket = None
            for candidate in (self.ghost_recent, self.ghost_protected):
                if candidate:
                    value = next(iter(candidate.values()))
                    if chosen is None or value[1] < chosen[1]:
                        chosen = value
                        bucket = candidate
            key, value = bucket.popitem(last=False)
            if bucket is self.ghost_recent:
                self.ghost_recent_bytes -= value[0]
            else:
                self.ghost_protected_bytes -= value[0]
            self.ghost_bytes -= value[0]

    def _adapt(self, kind):
        if self.capacity <= 0:
            return
        if kind == 1:
            if self.ghost_recent_bytes == 0:
                delta = self.capacity
            else:
                delta = max(1, min(self.capacity,
                                   self.ghost_protected_bytes // self.ghost_recent_bytes or 1))
            self.target = min(self.capacity, self.target + delta)
        else:
            if self.ghost_protected_bytes == 0:
                delta = self.capacity
            else:
                delta = max(1, min(self.capacity,
                                   self.ghost_recent_bytes // self.ghost_protected_bytes or 1))
            self.target = max(0, self.target - delta)

    def _remove_resident(self, key):
        size = self.recent.pop(key, None)
        if size is not None:
            self.recent_bytes -= size
            self.used -= size
            return size
        size = self.protected.pop(key, None)
        if size is not None:
            self.protected_bytes -= size
            self.used -= size
            return size
        return None

    def _evict_one(self, prefer_recent):
        if prefer_recent and self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, False)
            return key
        if self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, True)
            return key
        if self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, False)
            return key
        return None

    def _make_room(self, incoming, ghost_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            if ghost_kind == 1:
                prefer_recent = self.recent_bytes >= self.target
            elif ghost_kind == 2:
                prefer_recent = (self.recent_bytes > self.target or
                                 self.recent_bytes == self.target)
            else:
                prefer_recent = self.recent_bytes > self.target
            key = self._evict_one(prefer_recent)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key, size, now):
        key = int(key)
        size = max(0, int(size))
        _ = now

        if key in self.recent or key in self.protected:
            self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            if self.used + size > self.capacity:
                return evicted + [key]
            self._drop_ghost(key)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            return evicted

        if size <= 0 or size > self.capacity:
            return []

        if key in self.ghost_recent:
            ghost_kind = 1
        elif key in self.ghost_protected:
            ghost_kind = 2
        else:
            ghost_kind = 0

        if ghost_kind:
            self._adapt(ghost_kind)
            self._drop_ghost(key)

        evicted = self._make_room(size, ghost_kind)
        if self.used + size > self.capacity:
            return evicted

        if ghost_kind:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.recent[key] = size
            self.recent_bytes += size
        self.used += size
        return evicted
