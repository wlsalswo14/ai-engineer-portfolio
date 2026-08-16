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
        self.used_bytes = 0
        self.probation_bytes = 0
        self.protected_bytes = 0

    def _remember(self, ghost, key, size):
        ghost.pop(key, None)
        ghost[key] = size
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _forget_ghost(self, key):
        self.ghost_probation.pop(key, None)
        self.ghost_protected.pop(key, None)

    def _rebalance(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, record = self.protected.popitem(last=False)
            size = record[0]
            self.protected_bytes -= size
            self.probation[key] = record
            self.probation_bytes += size

    def _evict_one(self):
        probation_limit = self.capacity_bytes - self.protected_target
        if self.probation and (
            not self.protected or self.probation_bytes > probation_limit
        ):
            key, record = self.probation.popitem(last=False)
            size = record[0]
            self.probation_bytes -= size
            self._remember(self.ghost_probation, key, size)
        elif self.protected:
            key, record = self.protected.popitem(last=False)
            size = record[0]
            self.protected_bytes -= size
            self._remember(self.ghost_protected, key, size)
        elif self.probation:
            key, record = self.probation.popitem(last=False)
            size = record[0]
            self.probation_bytes -= size
            self._remember(self.ghost_probation, key, size)
        else:
            return None
        self.used_bytes -= size
        return key

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size, frequency, _ = self.protected.pop(key)
            self.protected[key] = (stored_size, min(255, frequency + 1), now)
            return []

        if key in self.probation:
            stored_size, frequency, _ = self.probation.pop(key)
            self.probation_bytes -= stored_size
            self.protected[key] = (stored_size, min(255, frequency + 1), now)
            self.protected_bytes += stored_size
            self._rebalance()
            return []

        if size <= 0 or size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        probation_revisit = key in self.ghost_probation
        protected_revisit = key in self.ghost_protected
        adjustment = max(1, self.capacity_bytes // 16, min(size, self.capacity_bytes))
        if probation_revisit:
            self.protected_target = min(
                self.capacity_bytes,
                self.protected_target + adjustment,
            )
        elif protected_revisit:
            self.protected_target = max(0, self.protected_target - adjustment)

        self._forget_ghost(key)
        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._evict_one()
            if old_key is None:
                break
            evicted.append(old_key)

        if self.used_bytes + size <= self.capacity_bytes:
            self.probation[key] = (size, 1, now)
            self.probation_bytes += size
            self.used_bytes += size
            self._rebalance()

        return evicted
