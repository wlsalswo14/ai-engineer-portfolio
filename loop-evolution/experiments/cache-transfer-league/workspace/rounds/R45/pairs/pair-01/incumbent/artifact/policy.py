from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.ghost_limit = 4096
        self.protected_target = self.capacity_bytes // 2
        self.protected_bytes = 0
        self.used_bytes = 0
        self.ghost_probation_bytes = 0
        self.ghost_protected_bytes = 0

    def _forget_ghost(self, key):
        value = self.ghost_probation.pop(key, None)
        if value is not None:
            self.ghost_probation_bytes -= value
        value = self.ghost_protected.pop(key, None)
        if value is not None:
            self.ghost_protected_bytes -= value

    def _remember(self, ghost, key, size):
        self._forget_ghost(key)
        size = max(1, int(size))
        ghost[key] = size
        if ghost is self.ghost_probation:
            self.ghost_probation_bytes += size
        else:
            self.ghost_protected_bytes += size
        while len(ghost) > self.ghost_limit:
            old_key, old_size = ghost.popitem(last=False)
            if ghost is self.ghost_probation:
                self.ghost_probation_bytes -= old_size
            else:
                self.ghost_protected_bytes -= old_size

    def _adapt(self, key):
        step = max(1, self.capacity_bytes // 16)
        if key in self.ghost_probation:
            denominator = max(1, self.ghost_probation_bytes)
            delta = max(
                step,
                min(
                    self.capacity_bytes,
                    (self.capacity_bytes * max(1, self.ghost_protected_bytes))
                    // denominator,
                ),
            )
            self.protected_target = min(
                self.capacity_bytes, self.protected_target + delta
            )
        elif key in self.ghost_protected:
            denominator = max(1, self.ghost_protected_bytes)
            delta = max(
                step,
                min(
                    self.capacity_bytes,
                    (self.capacity_bytes * max(1, self.ghost_probation_bytes))
                    // denominator,
                ),
            )
            self.protected_target = max(0, self.protected_target - delta)

    def _rebalance(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size

    def _evict_one(self):
        if self.probation:
            key, size = self.probation.popitem(last=False)
            self._remember(self.ghost_probation, key, size)
        elif self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self._remember(self.ghost_protected, key, size)
        else:
            return None
        self.used_bytes -= size
        return key

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            self._rebalance()
            return []

        if size <= 0 or self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        self._adapt(key)
        self._forget_ghost(key)

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._evict_one()
            if old_key is None:
                return evicted
            evicted.append(old_key)

        self.probation[key] = int(size)
        self.used_bytes += int(size)
        self._rebalance()
        return evicted
