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
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.used_bytes = 0

    def _remember(self, ghost, key):
        ghost.pop(key, None)
        ghost[key] = None
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
        if self.probation:
            key, record = self.probation.popitem(last=False)
            self.probation_bytes -= record[0]
            self._remember(self.ghost_probation, key)
        elif self.protected:
            key, record = self.protected.popitem(last=False)
            self.protected_bytes -= record[0]
            self._remember(self.ghost_protected, key)
        else:
            return None
        self.used_bytes -= record[0]
        return key

    def _touch(self, bucket, key, now):
        record = bucket.pop(key)
        record[1] = min(record[1] + 1, 255)
        record[2] = now
        bucket[key] = record

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            self._touch(self.protected, key, now)
            return []

        if key in self.probation:
            record = self.probation.pop(key)
            self.probation_bytes -= record[0]
            record[1] = min(record[1] + 1, 255)
            record[2] = now
            self.protected[key] = record
            self.protected_bytes += record[0]
            self._rebalance()
            return []

        if self.capacity_bytes == 0 or size <= 0 or size > self.capacity_bytes:
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
        self._forget_ghost(key)

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._evict_one()
            if old_key is None:
                return evicted
            evicted.append(old_key)

        self.probation[key] = [size, 1, now]
        self.probation_bytes += size
        self.used_bytes += size
        self._rebalance()
        return evicted
