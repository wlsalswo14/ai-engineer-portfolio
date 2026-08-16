from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.frequency = {}
        self.used_bytes = 0
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
        protected_bytes = sum(self.protected.values())
        while self.protected and protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.probation[key] = size
            protected_bytes -= size

    def _touch(self, key):
        self.frequency[key] = min(255, self.frequency.get(key, 0) + 1)

    def _evict_one(self):
        self._rebalance()
        if self.probation:
            victim, size = min(
                self.probation.items(),
                key=lambda item: (self.frequency.get(item[0], 0), next(iter(self.probation)).__hash__() if False else 0),
            )
            for key in self.probation:
                if self.frequency.get(key, 0) == self.frequency.get(victim, 0):
                    victim = key
                    break
            self.probation.pop(victim)
            self._remember(self.ghost_probation, victim)
        elif self.protected:
            victim, size = self.protected.popitem(last=False)
            self._remember(self.ghost_protected, victim)
        else:
            return None
        self.frequency.pop(victim, None)
        self.used_bytes -= size
        return victim

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored = self.protected.pop(key)
            self.protected[key] = stored
            self._touch(key)
            return []
        if key in self.probation:
            stored = self.probation.pop(key)
            self.protected[key] = stored
            self._touch(key)
            self._rebalance()
            return []
        if self.capacity_bytes == 0 or size <= 0 or size > self.capacity_bytes:
            return []
        if key in self.ghost_probation:
            step = max(1, self.capacity_bytes // 16)
            self.protected_target = min(self.capacity_bytes, self.protected_target + max(step, min(size, self.capacity_bytes)))
        elif key in self.ghost_protected:
            step = max(1, self.capacity_bytes // 16)
            self.protected_target = max(0, self.protected_target - max(step, min(size, self.capacity_bytes)))
        self._forget(key)
        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            victim = self._evict_one()
            if victim is None:
                break
            evicted.append(victim)
        self.probation[key] = size
        self.frequency[key] = 1
        self.used_bytes += size
        self._rebalance()
        return evicted
