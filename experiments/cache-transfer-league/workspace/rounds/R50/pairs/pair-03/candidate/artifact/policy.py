from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.t1_bytes = 0
        self.t2_bytes = 0
        self.b1_bytes = 0
        self.b2_bytes = 0
        self.target_t1 = self.capacity_bytes // 2
        self.ghost_limit = 4096

    def _remember(self, ghost, key, size):
        if ghost is self.b1:
            if key in ghost:
                self.b1_bytes -= ghost.pop(key)
            ghost[key] = size
            self.b1_bytes += size
            while len(ghost) > self.ghost_limit:
                _, old_size = ghost.popitem(last=False)
                self.b1_bytes -= old_size
        else:
            if key in ghost:
                self.b2_bytes -= ghost.pop(key)
            ghost[key] = size
            self.b2_bytes += size
            while len(ghost) > self.ghost_limit:
                _, old_size = ghost.popitem(last=False)
                self.b2_bytes -= old_size

    def _forget(self, key):
        if key in self.b1:
            self.b1_bytes -= self.b1.pop(key)
        if key in self.b2:
            self.b2_bytes -= self.b2.pop(key)

    def _evict_t1(self):
        if not self.t1:
            return None
        key, size = self.t1.popitem(last=False)
        self.t1_bytes -= size
        self._remember(self.b1, key, size)
        return key

    def _evict_t2(self):
        if not self.t2:
            return None
        key, size = self.t2.popitem(last=False)
        self.t2_bytes -= size
        self._remember(self.b2, key, size)
        return key

    def _replace(self, from_b2):
        if self.t1 and (self.t1_bytes > self.target_t1 or (from_b2 and self.t1_bytes == self.target_t1)):
            return self._evict_t1()
        if self.t2:
            return self._evict_t2()
        return self._evict_t1()

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.t1:
            stored_size = self.t1.pop(key)
            self.t1_bytes -= stored_size
            self.t2[key] = stored_size
            self.t2_bytes += stored_size
            return []

        if key in self.t2:
            stored_size = self.t2.pop(key)
            self.t2[key] = stored_size
            return []

        if size <= 0 or size > self.capacity_bytes:
            return []

        from_b1 = key in self.b1
        from_b2 = key in self.b2
        if from_b1:
            denominator = max(1, self.b1_bytes)
            delta = max(1, min(self.capacity_bytes, self.b2_bytes // denominator if self.b2_bytes else 1))
            self.target_t1 = min(self.capacity_bytes, self.target_t1 + max(size, delta))
        elif from_b2:
            denominator = max(1, self.b2_bytes)
            delta = max(1, min(self.capacity_bytes, self.b1_bytes // denominator if self.b1_bytes else 1))
            self.target_t1 = max(0, self.target_t1 - max(size, delta))

        self._forget(key)
        evicted = []
        while self.t1_bytes + self.t2_bytes + size > self.capacity_bytes:
            victim = self._replace(from_b2)
            if victim is None:
                break
            evicted.append(victim)

        self.t1[key] = size
        self.t1_bytes += size
        return evicted
