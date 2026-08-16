from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.ghost_limit = 4096
        self.p = self.capacity_bytes // 2
        self.t1_bytes = 0
        self.t2_bytes = 0
        self.used_bytes = 0

    def _remember(self, ghost, key, size):
        ghost.pop(key, None)
        ghost[key] = size
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _forget_ghost(self, key):
        self.b1.pop(key, None)
        self.b2.pop(key, None)

    def _replace(self, from_b2):
        if self.t1 and (self.t1_bytes > self.p or (from_b2 and self.t1_bytes == self.p)):
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self._remember(self.b1, key, size)
        elif self.t2:
            key, size = self.t2.popitem(last=False)
            self.t2_bytes -= size
            self._remember(self.b2, key, size)
        elif self.t1:
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self._remember(self.b1, key, size)
        else:
            return None
        self.used_bytes -= size
        return key

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

        if size <= 0 or self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        from_b2 = key in self.b2
        delta = max(1, self.capacity_bytes // 16)
        adjustment = max(delta, min(size, self.capacity_bytes))
        if key in self.b1:
            self.p = min(self.capacity_bytes, self.p + adjustment)
        elif from_b2:
            self.p = max(0, self.p - adjustment)
        self._forget_ghost(key)

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._replace(from_b2)
            if old_key is None:
                break
            evicted.append(old_key)

        if from_b2:
            self.t2[key] = size
            self.t2_bytes += size
        else:
            self.t1[key] = size
            self.t1_bytes += size
        self.used_bytes += size
        return evicted
