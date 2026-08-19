from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.ghost_limit = 4096
        self.protected_target = self.capacity_bytes // 2
        self.used_bytes = 0
        self.frequencies = {}
        self.frequency_limit = 16384

    def _record_request(self, key):
        if len(self.frequencies) >= self.frequency_limit and key not in self.frequencies:
            for current in list(self.frequencies):
                value = self.frequencies[current] // 2
                if value:
                    self.frequencies[current] = value
                else:
                    del self.frequencies[current]
        self.frequencies[key] = self.frequencies.get(key, 0) + 1

    def _remember(self, ghost, key):
        ghost.pop(key, None)
        ghost[key] = None
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _forget(self, key):
        self.ghost_probation.pop(key, None)
        self.ghost_protected.pop(key, None)

    def _rebalance(self):
        protected_bytes = sum(item[0] for item in self.protected.values())
        while self.protected and protected_bytes > self.protected_target:
            key, value = self.protected.popitem(last=False)
            self.probation[key] = value
            protected_bytes -= value[0]

    def _evict_one(self):
        if self.probation:
            key, value = self.probation.popitem(last=False)
            self._remember(self.ghost_probation, key)
        elif self.protected:
            key, value = self.protected.popitem(last=False)
            self._remember(self.ghost_protected, key)
        else:
            return None
        self.used_bytes -= value[0]
        return key

    def access(self, key: int, size: int, now: int) -> list[int]:
        self._record_request(key)

        if key in self.protected:
            stored_size, hits = self.protected.pop(key)
            self.protected[key] = (stored_size, hits + 1)
            return []

        if key in self.probation:
            stored_size, hits = self.probation.pop(key)
            self.protected[key] = (stored_size, hits + 1)
            self._rebalance()
            return []

        if size <= 0 or self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        step = max(1, self.capacity_bytes // 16)
        if key in self.ghost_probation:
            self.protected_target = min(
                self.capacity_bytes,
                self.protected_target + max(step, size),
            )
        elif key in self.ghost_protected:
            self.protected_target = max(
                0,
                self.protected_target - max(step, size),
            )
        self._forget(key)
        self._rebalance()

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            victim = self._evict_one()
            if victim is None:
                return evicted
            evicted.append(victim)

        self.probation[key] = (size, 1)
        self.used_bytes += size
        self._rebalance()
        return evicted
