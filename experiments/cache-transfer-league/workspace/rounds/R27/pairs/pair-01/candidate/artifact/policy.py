from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.used_bytes = 0
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.protected_target = self.capacity_bytes // 2
        self.ghost_limit = 4096
        self.mask = 4095
        self.sketch = [0] * (self.mask + 1)
        self.samples = 0
        self.mask64 = (1 << 64) - 1
        self.salts = (0x243F6A8885A308D3, 0x13198A2E03707344, 0xA4093822299F31D0, 0x082EFA98EC4E6C89)

    def _slot(self, key, salt):
        x = (int(key) ^ salt) & self.mask64
        x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & self.mask64
        x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & self.mask64
        return ((x ^ (x >> 31)) & self.mask)

    def _record(self, key):
        for salt in self.salts:
            index = self._slot(key, salt)
            if self.sketch[index] < 15:
                self.sketch[index] += 1
        self.samples += 1
        if self.samples >= 2048:
            self.samples = 0
            self.sketch = [(value + 1) // 2 for value in self.sketch]

    def _frequency(self, key):
        return min(self.sketch[self._slot(key, salt)] for salt in self.salts)

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

    def _victim(self):
        if self.probation:
            return next(iter(self.probation.items()))
        if self.protected:
            return next(iter(self.protected.items()))
        return None

    def _evict(self):
        if self.probation:
            key, size = self.probation.popitem(last=False)
            self._remember(self.ghost_probation, key)
        elif self.protected:
            key, size = self.protected.popitem(last=False)
            self._remember(self.ghost_protected, key)
        else:
            return None
        self.used_bytes -= size
        return key

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored = self.protected.pop(key)
            self.protected[key] = stored
            self._record(key)
            return []

        if key in self.probation:
            stored = self.probation.pop(key)
            self.protected[key] = stored
            self._record(key)
            self._rebalance()
            return []

        if self.capacity_bytes <= 0 or size <= 0 or size > self.capacity_bytes:
            return []

        self._record(key)
        step = max(1, self.capacity_bytes // 16)
        if key in self.ghost_probation:
            self.protected_target = min(self.capacity_bytes, self.protected_target + max(step, min(size, self.capacity_bytes)))
        elif key in self.ghost_protected:
            self.protected_target = max(0, self.protected_target - max(step, min(size, self.capacity_bytes)))
        self._forget(key)

        victim = self._victim()
        if victim is not None and self.used_bytes + size > self.capacity_bytes:
            if self._frequency(key) < self._frequency(victim[0]):
                return []

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old = self._evict()
            if old is None:
                break
            evicted.append(old)

        if self.used_bytes + size <= self.capacity_bytes:
            self.probation[key] = size
            self.used_bytes += size
            self._rebalance()
        return evicted
