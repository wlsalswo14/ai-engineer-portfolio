from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0
        self.protected_target = self.capacity_bytes // 2
        self.ghost_limit = 4096
        self.requests = 0

    def _tick(self):
        self.requests += 1

    def _remember(self, key, size, segment):
        self.ghost.pop(key, None)
        self.ghost[key] = (size, segment)
        while len(self.ghost) > self.ghost_limit:
            self.ghost.popitem(last=False)

    def _rebalance(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size

    def _evict_one(self):
        if self.probation:
            key, size = self.probation.popitem(last=False)
            segment = 0
        elif self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            segment = 1
        else:
            return None
        self.used_bytes -= size
        self._remember(key, size, segment)
        return key

    def _adapt(self, segment):
        step = max(1, self.capacity_bytes // 32)
        if segment:
            self.protected_target = min(
                (self.capacity_bytes * 3) // 4,
                self.protected_target + step,
            )
        else:
            self.protected_target = max(
                self.capacity_bytes // 4,
                self.protected_target - step,
            )

    def access(self, key: int, size: int, now: int) -> list[int]:
        self._tick()

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

        size = max(0, int(size))
        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        ghost_entry = self.ghost.pop(key, None)
        if ghost_entry is not None:
            self._adapt(ghost_entry[1])

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            victim = self._evict_one()
            if victim is None:
                break
            evicted.append(victim)

        if ghost_entry is not None and ghost_entry[1]:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.probation[key] = size
        self.used_bytes += size
        self._rebalance()
        return evicted
