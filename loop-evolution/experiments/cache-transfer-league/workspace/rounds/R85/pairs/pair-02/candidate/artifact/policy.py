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
        self.ghost_recent_bytes = 0
        self.ghost_frequent_bytes = 0
        self.used = 0
        self.target = self.capacity // 2
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096
        self.serial = 0

    def _remember_ghost(self, key, size, kind):
        self._drop_ghost(key)
        self.serial += 1
        value = (size, self.serial)
        if kind == 1:
            self.ghost_recent[key] = value
            self.ghost_recent_bytes += size
        else:
            self.ghost_frequent[key] = value
            self.ghost_frequent_bytes += size
        self._trim_ghosts()

    def _drop_ghost(self, key):
        value = self.ghost_recent.pop(key, None)
        if value is not None:
            self.ghost_recent_bytes -= value[0]
        value = self.ghost_frequent.pop(key, None)
        if value is not None:
            self.ghost_frequent_bytes -= value[0]

    def _trim_ghosts(self):
        while (self.ghost_recent_bytes + self.ghost_frequent_bytes > self.ghost_limit or
               len(self.ghost_recent) + len(self.ghost_frequent) > self.ghost_count_limit):
            source = None
            if self.ghost_recent:
                source = self.ghost_recent
            if self.ghost_frequent:
                if source is None:
                    source = self.ghost_frequent
                else:
                    recent_key = next(iter(self.ghost_recent))
                    frequent_key = next(iter(self.ghost_frequent))
                    if self.ghost_frequent[frequent_key][1] < self.ghost_recent[recent_key][1]:
                        source = self.ghost_frequent
            _, value = source.popitem(last=False)
            if source is self.ghost_recent:
                self.ghost_recent_bytes -= value[0]
            else:
                self.ghost_frequent_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        if kind == 1:
            a = self.ghost_recent_bytes
            b = self.ghost_frequent_bytes
            delta = self.capacity if a == 0 else max(1, min(self.capacity, b // a or 1))
            self.target = min(self.capacity, self.target + delta)
        else:
            a = self.ghost_frequent_bytes
            b = self.ghost_recent_bytes
            delta = self.capacity if a == 0 else max(1, min(self.capacity, b // a or 1))
            self.target = max(0, self.target - delta)

    def _evict_one(self, prefer_recent):
        if prefer_recent and self.recent:
            source = self.recent
        elif self.frequent:
            source = self.frequent
        elif self.recent:
            source = self.recent
        else:
            return None
        key, size = source.popitem(last=False)
        if source is self.recent:
            self.recent_bytes -= size
            kind = 1
        else:
            self.frequent_bytes -= size
            kind = 2
        self.used -= size
        self._remember_ghost(key, size, kind)
        return key

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

    def _rebalance(self):
        protected_limit = self.capacity - self.target
        while self.frequent_bytes > protected_limit and self.frequent:
            key, size = self.frequent.popitem(last=False)
            self.frequent_bytes -= size
            self.recent[key] = size
            self.recent_bytes += size

    def access(self, key, size, now):
        key = int(key)
        size = int(size)

        if key in self.recent:
            if size <= 0 or size > self.capacity:
                return []
            old_size = self.recent.pop(key)
            self.recent_bytes -= old_size
            self.used -= old_size
            evicted = self._make_room(size, 0)
            if self.used + size > self.capacity:
                self.recent[key] = old_size
                self.recent_bytes += old_size
                self.used += old_size
                return evicted
            self._drop_ghost(key)
            self.frequent[key] = size
            self.frequent_bytes += size
            self.used += size
            self._rebalance()
            return evicted

        if key in self.frequent:
            self.frequent.move_to_end(key)
            return []

        if size <= 0 or size > self.capacity:
            return []

        ghost_kind = 1 if key in self.ghost_recent else 2 if key in self.ghost_frequent else 0
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
        self._rebalance()
        return evicted
