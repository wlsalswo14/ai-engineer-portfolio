from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0
        self.protected_target = self.capacity_bytes // 2
        self.ghost_limit = 4096

    def _remember(self, ghost, key):
        ghost.pop(key, None)
        ghost[key] = None
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _forget(self, key):
        self.ghost_probation.pop(key, None)
        self.ghost_protected.pop(key, None)

    def _rebalance(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size

    def _evict_one(self):
        if self.probation:
            key, size = self.probation.popitem(last=False)
            self._remember(self.ghost_probation, key)
        elif self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self._remember(self.ghost_protected, key)
        else:
            return None
        self.used_bytes -= size
        return key

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored = self.protected.pop(key)
            self.protected[key] = stored
            return []

        if key in self.probation:
            stored = self.probation.pop(key)
            self.protected[key] = stored
            self.protected_bytes += stored
            self._rebalance()
            return []

        if size <= 0 or size > self.capacity_bytes:
            return []

        step = max(1, self.capacity_bytes // 16)
        if key in self.ghost_probation:
            self.protected_target = min(
                self.capacity_bytes,
                self.protected_target + max(step, min(size, self.capacity_bytes)),
            )
        elif key in self.ghost_protected:
            self.protected_target = max(
                0,
                self.protected_target - max(step, min(size, self.capacity_bytes)),
            )
        self._forget(key)

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old = self._evict_one()
            if old is None:
                break
            evicted.append(old)

        self.probation[key] = size
        self.used_bytes += size
        self._rebalance()
        return evicted
