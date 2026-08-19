from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.t1_bytes = 0
        self.t2_bytes = 0
        self.ghost_bytes = 0
        self.target = 0

    def _remember(self, ghosts, key, size):
        if key in self.b1:
            self.ghost_bytes -= self.b1.pop(key)
        if key in self.b2:
            self.ghost_bytes -= self.b2.pop(key)
        ghosts[key] = size
        self.ghost_bytes += size
        limit = 2 * self.capacity_bytes
        while self.ghost_bytes > limit:
            if self.b1:
                _, old_size = self.b1.popitem(last=False)
            elif self.b2:
                _, old_size = self.b2.popitem(last=False)
            else:
                break
            self.ghost_bytes -= old_size

    def _replace(self, from_b2):
        if self.t1 and (self.t1_bytes > self.target or
                        (from_b2 and self.t1_bytes == self.target)):
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self._remember(self.b1, key, size)
            return key, size
        if self.t2:
            key, size = self.t2.popitem(last=False)
            self.t2_bytes -= size
            self._remember(self.b2, key, size)
            return key, size
        if self.t1:
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self._remember(self.b1, key, size)
            return key, size
        return None, 0

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

        if size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        from_b2 = key in self.b2
        if key in self.b1:
            remembered = self.b1.pop(key)
            self.ghost_bytes -= remembered
            self.target = min(self.capacity_bytes,
                              self.target + max(1, size))
            destination = self.t2
        elif from_b2:
            remembered = self.b2.pop(key)
            self.ghost_bytes -= remembered
            self.target = max(0, self.target - max(1, size))
            destination = self.t2
        else:
            destination = self.t1

        evicted = []
        while self.t1_bytes + self.t2_bytes + size > self.capacity_bytes:
            old_key, _ = self._replace(from_b2)
            if old_key is None:
                break
            evicted.append(old_key)

        destination[key] = size
        if destination is self.t1:
            self.t1_bytes += size
        else:
            self.t2_bytes += size
        return evicted
