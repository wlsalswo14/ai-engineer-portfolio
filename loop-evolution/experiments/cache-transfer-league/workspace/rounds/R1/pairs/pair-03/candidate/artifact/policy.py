from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.protected_bytes = 0
        self.used_bytes = 0
        self._tick = 0

    def _age(self):
        for cache in (self.probation, self.protected):
            for record in cache.values():
                record[1] = max(1, record[1] // 2)

    def _touch(self, cache, key):
        record = cache.pop(key)
        record[1] = min(255, record[1] + 1)
        record[2] = self._tick
        cache[key] = record

    def _rebalance(self):
        target = (self.capacity_bytes * 2) // 3
        while self.protected and self.protected_bytes > target:
            key, record = self.protected.popitem(last=False)
            self.protected_bytes -= record[0]
            self.probation[key] = record

    def _victim(self, cache):
        return min(cache.items(), key=lambda item: (item[1][1], item[1][2]))[0]

    def _make_room(self, size):
        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            cache = self.probation if self.probation else self.protected
            if not cache:
                break
            key = self._victim(cache)
            record = cache.pop(key)
            self.used_bytes -= record[0]
            if cache is self.protected:
                self.protected_bytes -= record[0]
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        self._tick += 1
        if self._tick % 256 == 0:
            self._age()

        if key in self.protected:
            self._touch(self.protected, key)
            return []

        if key in self.probation:
            record = self.probation.pop(key)
            record[1] = min(255, record[1] + 1)
            record[2] = self._tick
            self.protected[key] = record
            self.protected_bytes += record[0]
            self._rebalance()
            return []

        if size < 0 or size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        evicted = self._make_room(size)
        self.probation[key] = [size, 1, self._tick]
        self.used_bytes += size
        self._rebalance()
        return evicted
