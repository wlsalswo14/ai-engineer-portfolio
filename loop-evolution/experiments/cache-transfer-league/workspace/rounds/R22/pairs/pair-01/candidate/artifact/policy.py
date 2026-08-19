from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.recent = OrderedDict()
        self.hot = OrderedDict()
        self.used_bytes = 0
        self.clock = 0
        self.accesses = 0

    def _age(self):
        for key in list(self.hot):
            entry = self.hot[key]
            entry[1] = max(1, entry[1] // 2)
            if entry[1] <= 1:
                self.hot.pop(key)
                self.recent[key] = entry
        for entry in self.recent.values():
            entry[1] = max(1, entry[1] // 2)

    def _evict_one(self):
        if self.recent:
            key, entry = self.recent.popitem(last=False)
        elif self.hot:
            key = min(self.hot, key=lambda k: (self.hot[k][1], self.hot[k][2]))
            entry = self.hot.pop(key)
        else:
            return None
        self.used_bytes -= entry[0]
        return key

    def access(self, key: int, size: int, now: int) -> list[int]:
        self.clock += 1
        self.accesses += 1
        entry = self.hot.get(key)
        if entry is not None:
            entry[1] += 1
            entry[2] = self.clock
            self.hot.move_to_end(key)
            if self.accesses % 64 == 0:
                self._age()
            return []

        entry = self.recent.get(key)
        if entry is not None:
            self.recent.pop(key)
            entry[1] += 1
            entry[2] = self.clock
            self.hot[key] = entry
            if self.accesses % 64 == 0:
                self._age()
            return []

        size = max(0, size)
        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            if self.accesses % 64 == 0:
                self._age()
            return []

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            victim = self._evict_one()
            if victim is None:
                break
            evicted.append(victim)

        self.recent[key] = [size, 1, self.clock]
        self.used_bytes += size
        if self.accesses % 64 == 0:
            self._age()
        return evicted
