class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self._items = {}
        self._ghost = {}
        self._freq = {}
        self._clock = 0
        self._bytes = 0
        self._ghost_limit = 2048

    def _bump(self, key):
        value = self._freq.get(key, 0) + 1
        self._freq[key] = min(value, 1073741824)
        if len(self._freq) > 8192:
            for old_key in list(self._freq):
                reduced = self._freq[old_key] // 2
                if reduced:
                    self._freq[old_key] = reduced
                else:
                    del self._freq[old_key]

    def _remember_ghost(self, key, frequency):
        self._ghost[key] = (max(1, frequency), self._clock)
        if len(self._ghost) > self._ghost_limit:
            oldest = min(self._ghost, key=lambda k: (self._ghost[k][1], self._ghost[k][0], k))
            del self._ghost[oldest]

    def _rank(self, key, item):
        age = max(0, min(4095, self._clock - item[3]))
        recency = 4096 - age
        utility = (item[2] + 1) * 4096 + recency
        density = (utility * 1048576) // (item[0] + 1)
        return (density, item[2], item[3], item[0], key)

    def _rebalance(self):
        target = (self.capacity * 7) // 10
        protected_bytes = sum(item[0] for item in self._items.values() if item[1] == 1)
        while protected_bytes > target:
            protected = [(key, item) for key, item in self._items.items() if item[1] == 1]
            if not protected:
                break
            key, item = min(protected, key=lambda pair: self._rank(pair[0], pair[1]))
            item[1] = 0
            protected_bytes -= item[0]

    def _enforce(self):
        evicted = []
        while self._bytes > self.capacity and self._items:
            probation = [(key, item) for key, item in self._items.items() if item[1] == 0]
            candidates = probation if probation else list(self._items.items())
            victim_key, victim = min(candidates, key=lambda pair: self._rank(pair[0], pair[1]))
            del self._items[victim_key]
            self._bytes -= victim[0]
            self._remember_ghost(victim_key, victim[2])
            evicted.append(victim_key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        self._clock += 1
        amount = max(0, int(size))
        self._bump(key)
        item = self._items.get(key)

        if item is not None:
            old_size = item[0]
            if amount > self.capacity:
                del self._items[key]
                self._bytes -= old_size
                self._remember_ghost(key, item[2])
                return [key]
            item[0] = amount
            item[2] = max(1, self._freq.get(key, 1))
            item[3] = self._clock
            item[1] = 1
            self._bytes += amount - old_size
            self._rebalance()
            return self._enforce()

        ghost = self._ghost.pop(key, None)
        if amount > self.capacity:
            return []
        segment = 1 if ghost is not None else 0
        self._items[key] = [amount, segment, max(1, self._freq.get(key, 1)), self._clock]
        self._bytes += amount
        self._rebalance()
        return self._enforce()
