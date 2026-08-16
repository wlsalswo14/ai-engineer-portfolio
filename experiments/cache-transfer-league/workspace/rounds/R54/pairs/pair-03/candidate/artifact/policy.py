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
        self.p = self.capacity_bytes // 2
        self.ghost_limit = 4096

    def _remember(self, ghost, key):
        ghost.pop(key, None)
        ghost[key] = None
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _forget(self, key):
        self.b1.pop(key, None)
        self.b2.pop(key, None)

    def _replace(self, incoming):
        evicted = None
        if self.t1 and (self.t1_bytes > self.p or (incoming in self.b2 and self.t1_bytes == self.p)):
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self._remember(self.b1, key)
            evicted = key
        elif self.t2:
            key, size = self.t2.popitem(last=False)
            self.t2_bytes -= size
            self._remember(self.b2, key)
            evicted = key
        elif self.t1:
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self._remember(self.b1, key)
            evicted = key
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.t1:
            stored = self.t1.pop(key)
            self.t1_bytes -= stored
            self.t2[key] = stored
            self.t2_bytes += stored
            return []
        if key in self.t2:
            stored = self.t2.pop(key)
            self.t2[key] = stored
            return []
        if size <= 0 or size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        in_b1 = key in self.b1
        in_b2 = key in self.b2
        if in_b1:
            delta = max(1, self.capacity_bytes // 16)
            self.p = min(self.capacity_bytes, self.p + delta)
        elif in_b2:
            delta = max(1, self.capacity_bytes // 16)
            self.p = max(0, self.p - delta)

        self._forget(key)
        evicted = []
        while self.t1_bytes + self.t2_bytes + size > self.capacity_bytes:
            old = self._replace(key)
            if old is None:
                break
            evicted.append(old)

        if in_b1 or in_b2:
            self.t2[key] = size
            self.t2_bytes += size
        else:
            self.t1[key] = size
            self.t1_bytes += size
        return evicted
