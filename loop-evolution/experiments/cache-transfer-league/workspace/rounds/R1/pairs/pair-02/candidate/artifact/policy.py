from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0
        self.clock = 0
        self.operations = 0
        self.protected_hits = 0
        self.probation_hits = 0
        self.protected_ratio = 50
        self.ghost_limit = 4096

    def _protected_target(self):
        if self.capacity_bytes == 0:
            return 0
        target = self.capacity_bytes * self.protected_ratio // 100
        return max(1, min(self.capacity_bytes, target))

    def _rebalance(self):
        target = self._protected_target()
        while self.protected and self.protected_bytes > target:
            key, record = self.protected.popitem(last=False)
            size, stamp = record
            self.protected_bytes -= size
            self.probation[key] = (size, stamp)

    def _remember(self, key):
        self.ghost.pop(key, None)
        self.ghost[key] = None
        while len(self.ghost) > self.ghost_limit:
            self.ghost.popitem(last=False)

    def _observe(self, key):
        del key
        self.clock += 1
        self.operations += 1
        if self.operations % 256 == 0:
            if self.protected_hits > self.probation_hits * 2:
                self.protected_ratio = min(80, self.protected_ratio + 5)
            elif self.probation_hits > self.protected_hits * 2:
                self.protected_ratio = max(25, self.protected_ratio - 5)
            self.protected_hits = 0
            self.probation_hits = 0

    def _evict_probation(self):
        key, record = self.probation.popitem(last=False)
        size, _ = record
        self.used_bytes -= size
        self._remember(key)
        return key

    def _make_room(self, required_bytes):
        evicted = []
        self._rebalance()
        while self.used_bytes + required_bytes > self.capacity_bytes:
            if self.probation:
                evicted.append(self._evict_probation())
            elif self.protected:
                key, record = self.protected.popitem(last=False)
                size, stamp = record
                self.protected_bytes -= size
                self.probation[key] = (size, stamp)
            else:
                break
        return evicted

    def _remove_protected(self, key):
        size, _ = self.protected.pop(key)
        self.protected_bytes -= size
        self.used_bytes -= size

    def _remove_probation(self, key):
        size, _ = self.probation.pop(key)
        self.used_bytes -= size

    def access(self, key: int, size: int, now: int) -> list[int]:
        del now
        size = max(0, int(size))
        self._observe(key)

        if key in self.protected:
            old_size, _ = self.protected.pop(key)
            if size > self.capacity_bytes:
                self.protected_bytes -= old_size
                self.used_bytes -= old_size
                self._remember(key)
                return [key]
            self.protected[key] = (size, self.clock)
            self.protected_bytes += size - old_size
            self.used_bytes += size - old_size
            self.protected_hits += 1
            return self._make_room(0)

        if key in self.probation:
            old_size, _ = self.probation.pop(key)
            if size > self.capacity_bytes:
                self.used_bytes -= old_size
                self._remember(key)
                return [key]
            self.probation[key] = (size, self.clock)
            self.used_bytes += size - old_size
            self.probation_hits += 1
            moved_size, moved_stamp = self.probation.pop(key)
            self.protected[key] = (moved_size, moved_stamp)
            self.protected_bytes += moved_size
            self._rebalance()
            return self._make_room(0)

        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        ghost_hit = key in self.ghost
        if ghost_hit:
            self.ghost.pop(key, None)

        evicted = self._make_room(size)
        record = (size, self.clock)
        if ghost_hit:
            self.protected[key] = record
            self.protected_bytes += size
        else:
            self.probation[key] = record
        self.used_bytes += size
        self._rebalance()
        return evicted
