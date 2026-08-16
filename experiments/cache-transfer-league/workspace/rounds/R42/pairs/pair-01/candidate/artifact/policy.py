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

    def _remember(self, ghost, key, size):
        self.ghost_probation.pop(key, None)
        self.ghost_protected.pop(key, None)
        ghost[key] = size
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _forget_ghost(self, key):
        self.ghost_probation.pop(key, None)
        self.ghost_protected.pop(key, None)

    def _rebalance(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, entry = self.protected.popitem(last=False)
            self.protected_bytes -= entry[0]
            self.probation[key] = entry

    def _evict_one(self):
        if self.probation:
            key, entry = self.probation.popitem(last=False)
            self._remember(self.ghost_probation, key, entry[0])
        elif self.protected:
            key, entry = self.protected.popitem(last=False)
            self.protected_bytes -= entry[0]
            self._remember(self.ghost_protected, key, entry[0])
        else:
            return None
        self.used_bytes -= entry[0]
        return key

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size, hits = self.protected.pop(key)
            self.protected[key] = (stored_size, hits + 1)
            return []

        if key in self.probation:
            stored_size, hits = self.probation.pop(key)
            self.protected[key] = (stored_size, hits + 1)
            self.protected_bytes += stored_size
            self._rebalance()
            return []

        if size <= 0 or self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        step = max(1, self.capacity_bytes // 16)
        if key in self.ghost_probation:
            ghost_size = self.ghost_probation[key]
            self.protected_target = min(
                self.capacity_bytes,
                self.protected_target + max(step, min(ghost_size, self.capacity_bytes)),
            )
        elif key in self.ghost_protected:
            ghost_size = self.ghost_protected[key]
            self.protected_target = max(
                0,
                self.protected_target - max(step, min(ghost_size, self.capacity_bytes)),
            )
        self._forget_ghost(key)

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._evict_one()
            if old_key is None:
                return evicted
            evicted.append(old_key)

        self.probation[key] = (size, 1)
        self.used_bytes += size
        self._rebalance()
        return evicted
