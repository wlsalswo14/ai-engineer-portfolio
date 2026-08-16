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
        self.ghost_recent_bytes = 0
        self.ghost_frequent_bytes = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096
        self.serial = 0

    def _drop_ghost(self, key):
        value = self.ghost_recent.pop(key, None)
        if value is not None:
            amount = value[0]
            self.ghost_bytes -= amount
            self.ghost_recent_bytes -= amount
            return
        value = self.ghost_frequent.pop(key, None)
        if value is not None:
            amount = value[0]
            self.ghost_bytes -= amount
            self.ghost_frequent_bytes -= amount

    def _remember_ghost(self, key, size, kind):
        self._drop_ghost(key)
        self.serial += 1
        value = (max(1, int(size)), self.serial)
        if kind == 1:
            self.ghost_recent[key] = value
            self.ghost_recent_bytes += value[0]
        else:
            self.ghost_frequent[key] = value
            self.ghost_frequent_bytes += value[0]
        self.ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_recent) + len(self.ghost_frequent) > self.ghost_count_limit):
            source = None
            oldest = None
            for ghosts in (self.ghost_recent, self.ghost_frequent):
                if ghosts:
                    value = next(iter(ghosts.values()))
                    if oldest is None or value[1] < oldest[1]:
                        source = ghosts
                        oldest = value
            key, value = source.popitem(last=False)
            amount = value[0]
            self.ghost_bytes -= amount
            if source is self.ghost_recent:
                self.ghost_recent_bytes -= amount
            else:
                self.ghost_frequent_bytes -= amount

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        if kind == 1:
            if self.ghost_recent_bytes == 0:
                delta = self.capacity
            else:
                delta = max(1, min(self.capacity,
                                   self.ghost_frequent_bytes // self.ghost_recent_bytes or 1))
            self.target = min(self.capacity, self.target + delta)
        else:
            if self.ghost_frequent_bytes == 0:
                delta = self.capacity
            else:
                delta = max(1, min(self.capacity,
                                   self.ghost_recent_bytes // self.ghost_frequent_bytes or 1))
            self.target = max(0, self.target - delta)

    def _remove_resident(self, key):
        value = self.recent.pop(key, None)
        if value is not None:
            self.recent_bytes -= value
            self.used -= value
            return value
        value = self.frequent.pop(key, None)
        if value is not None:
            self.frequent_bytes -= value
            self.used -= value
            return value
        return None

    def _evict_one(self, prefer_recent):
        if prefer_recent and self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 1)
            return key
        if self.frequent:
            key, size = self.frequent.popitem(last=False)
            self.frequent_bytes -= size
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

    def _make_room(self, incoming, ghost_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            if ghost_kind == 1:
                prefer_recent = self.recent_bytes >= self.target
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

        if key in self.recent or key in self.frequent:
            self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            if self.used + size > self.capacity:
                return evicted + [key]
            self._drop_ghost(key)
            self.frequent[key] = size
            self.frequent_bytes += size
            self.used += size
            return evicted

        if size <= 0 or size > self.capacity:
            return []

        if key in self.ghost_recent:
            ghost_kind = 1
        elif key in self.ghost_frequent:
            ghost_kind = 2
        else:
            ghost_kind = 0

        if ghost_kind:
            self._adjust_target(ghost_kind)
            self._drop_ghost(key)

        evicted = self._make_room(size, ghost_kind)
        if self.used + size > self.capacity:
            return evicted

        if ghost_kind:
            self.frequent[key] = size
            self.frequent_bytes += size
        else:
            self.recent[key] = size
            self.recent_bytes += size
        self.used += size
        return evicted
