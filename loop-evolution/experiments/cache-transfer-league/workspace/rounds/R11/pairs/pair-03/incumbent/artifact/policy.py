from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost = OrderedDict()
        self.used_bytes = 0
        self.ghost_limit = max(64, min(4096, self.capacity_bytes))

    def _protected_bytes(self):
        return sum(self.protected.values())

    def _rebalance(self):
        target = self.capacity_bytes // 2
        while self.protected and self._protected_bytes() > target:
            key, size = self.protected.popitem(last=False)
            self.probation[key] = size

    def _remember(self, key):
        self.ghost.pop(key, None)
        self.ghost[key] = None
        while len(self.ghost) > self.ghost_limit:
            self.ghost.popitem(last=False)

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.protected[key] = stored_size
            self._rebalance()
            return []

        if size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        promoted = key in self.ghost
        self.ghost.pop(key, None)
        evicted = []

        while self.used_bytes + size > self.capacity_bytes:
            if self.probation:
                old_key, old_size = self.probation.popitem(last=False)
            elif self.protected:
                old_key, old_size = self.protected.popitem(last=False)
            else:
                break
            self.used_bytes -= old_size
            self._remember(old_key)
            evicted.append(old_key)

        if promoted:
            self.protected[key] = size
        else:
            self.probation[key] = size
        self.used_bytes += size
        self._rebalance()
        return evicted
