from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.p = 0
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.t1_bytes = 0
        self.t2_bytes = 0
        self.b1_bytes = 0
        self.b2_bytes = 0

    def _discard_ghost(self, key):
        size = self.b1.pop(key, None)
        if size is not None:
            self.b1_bytes -= size
        size = self.b2.pop(key, None)
        if size is not None:
            self.b2_bytes -= size

    def _trim_ghosts(self):
        limit = max(1, 2 * (len(self.t1) + len(self.t2)))
        while (len(self.b1) + len(self.b2) > limit or
               self.b1_bytes + self.b2_bytes > 2 * self.capacity_bytes):
            if self.b1:
                _, size = self.b1.popitem(last=False)
                self.b1_bytes -= size
            elif self.b2:
                _, size = self.b2.popitem(last=False)
                self.b2_bytes -= size
            else:
                break

    def _remember(self, ghost, key, size):
        self._discard_ghost(key)
        ghost[key] = size
        if ghost is self.b1:
            self.b1_bytes += size
        else:
            self.b2_bytes += size
        self._trim_ghosts()

    def _replace(self, incoming_size, from_b2):
        evicted = []
        while self.t1_bytes + self.t2_bytes + incoming_size > self.capacity_bytes:
            if self.t1 and (self.t1_bytes > self.p or
                            (from_b2 and self.t1_bytes == self.p)):
                old_key, old_size = self.t1.popitem(last=False)
                self.t1_bytes -= old_size
                self._remember(self.b1, old_key, old_size)
            elif self.t2:
                old_key, old_size = self.t2.popitem(last=False)
                self.t2_bytes -= old_size
                self._remember(self.b2, old_key, old_size)
            elif self.t1:
                old_key, old_size = self.t1.popitem(last=False)
                self.t1_bytes -= old_size
                self._remember(self.b1, old_key, old_size)
            else:
                break
            evicted.append(old_key)
        return evicted

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

        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        if key in self.b1:
            delta = max(1, self.b2_bytes // max(1, self.b1_bytes))
            self.p = min(self.capacity_bytes, self.p + delta)
            self._discard_ghost(key)
            evicted = self._replace(size, False)
            if self.t1_bytes + self.t2_bytes + size <= self.capacity_bytes:
                self.t2[key] = size
                self.t2_bytes += size
            return evicted

        if key in self.b2:
            delta = max(1, self.b1_bytes // max(1, self.b2_bytes))
            self.p = max(0, self.p - delta)
            self._discard_ghost(key)
            evicted = self._replace(size, True)
            if self.t1_bytes + self.t2_bytes + size <= self.capacity_bytes:
                self.t2[key] = size
                self.t2_bytes += size
            return evicted

        evicted = self._replace(size, False)
        if self.t1_bytes + self.t2_bytes + size <= self.capacity_bytes:
            self.t1[key] = size
            self.t1_bytes += size
        return evicted
