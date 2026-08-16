from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        self.capacity = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.used = 0
        self.target = self.capacity // 2
        self.ghost_bytes = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096

    def _discard_ghost(self, key):
        value = self.ghost_recent.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value
        value = self.ghost_frequent.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value

    def _remember_ghost(self, key, size, frequent):
        self._discard_ghost(key)
        size = max(1, int(size))
        ghosts = self.ghost_frequent if frequent else self.ghost_recent
        ghosts[key] = size
        self.ghost_bytes += size
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_recent) + len(self.ghost_frequent) > self.ghost_count_limit):
            source = None
            if self.ghost_recent and self.ghost_frequent:
                source = (self.ghost_recent if
                          next(iter(self.ghost_recent.values())) <=
                          next(iter(self.ghost_frequent.values())) else
                          self.ghost_frequent)
            elif self.ghost_recent:
                source = self.ghost_recent
            else:
                source = self.ghost_frequent
            _, size = source.popitem(last=False)
            self.ghost_bytes -= size

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        recent_ghost_bytes = sum(self.ghost_recent.values())
        frequent_ghost_bytes = sum(self.ghost_frequent.values())
        if kind == 1:
            delta = (self.capacity if recent_ghost_bytes == 0 else
                     max(1, min(self.capacity,
                                frequent_ghost_bytes // recent_ghost_bytes or 1)))
            self.target = min(self.capacity, self.target + delta)
        else:
            delta = (self.capacity if frequent_ghost_bytes == 0 else
                     max(1, min(self.capacity,
                                recent_ghost_bytes // frequent_ghost_bytes or 1)))
            self.target = max(0, self.target - delta)

    def _remove_resident(self, key):
        size = self.recent.pop(key, None)
        if size is not None:
            self.recent_bytes -= size
            self.used -= size
            return size, False
        size = self.frequent.pop(key, None)
        if size is not None:
            self.frequent_bytes -= size
            self.used -= size
            return size, True
        return None

    def _evict_one(self, prefer_recent):
        if prefer_recent and self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, False)
            return key
        if self.frequent:
            key, size = self.frequent.popitem(last=False)
            self.frequent_bytes -= size
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

    def _make_room(self, incoming, kind):
        evicted = []
        while self.used + incoming > self.capacity:
            prefer_recent = self.recent_bytes > self.target
            if kind == 1 and self.recent_bytes >= self.target:
                prefer_recent = True
            elif kind == 2 and self.recent_bytes > self.target:
                prefer_recent = True
            key = self._evict_one(prefer_recent)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key, size, now):
        key = int(key)
        size = max(0, int(size))

        resident = key in self.recent or key in self.frequent
        if resident:
            self._remove_resident(key)
            if size == 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            if self.used + size > self.capacity:
                return evicted + [key]
            self._discard_ghost(key)
            self.frequent[key] = size
            self.frequent_bytes += size
            self.used += size
            return evicted

        kind = 1 if key in self.ghost_recent else 2 if key in self.ghost_frequent else 0
        if size == 0 or size > self.capacity:
            return []
        if kind:
            self._adjust_target(kind)
            self._discard_ghost(key)

        evicted = self._make_room(size, kind)
        if self.used + size > self.capacity:
            return evicted
        if kind:
            self.frequent[key] = size
            self.frequent_bytes += size
        else:
            self.recent[key] = size
            self.recent_bytes += size
        self.used += size
        return evicted
