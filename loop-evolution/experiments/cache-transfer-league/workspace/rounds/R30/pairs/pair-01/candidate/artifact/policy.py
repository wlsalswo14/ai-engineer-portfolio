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
        self.target_t2 = self.capacity_bytes // 2
        self.ghost_limit = 4096

    def _drop_ghost(self, key):
        size = self.b1.pop(key, None)
        if size is not None:
            self.b1_bytes -= size
        size = self.b2.pop(key, None)
        if size is not None:
            self.b2_bytes -= size

    def _remember(self, ghost, key, size):
        self._drop_ghost(key)
        ghost[key] = size
        if ghost is self.b1:
            self.b1_bytes += size
        else:
            self.b2_bytes += size
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.b1_bytes + self.b2_bytes > self.capacity_bytes or
               len(self.b1) + len(self.b2) > self.ghost_limit):
            if self.b1 and (not self.b2 or self.b1_bytes >= self.b2_bytes):
                self.b1.popitem(last=False)
                key, size = next(reversed(self.b1.items()), (None, None))
                if key is not None:
                    pass
                self.b1_bytes = sum(self.b1.values())
            elif self.b2:
                self.b2.popitem(last=False)
                self.b2_bytes = sum(self.b2.values())
            else:
                break

    def _adaptation(self, own_bytes, other_bytes, size):
        base = max(1, min(self.capacity_bytes, max(size, self.capacity_bytes // 32)))
        if own_bytes <= 0:
            return base
        ratio = max(1, other_bytes // own_bytes)
        return min(self.capacity_bytes, base * ratio)

    def _replace(self, incoming_size, from_b2):
        evicted = []
        while self.t1_bytes + self.t2_bytes + incoming_size > self.capacity_bytes:
            choose_t1 = self.t1 and (self.t1_bytes > self.target_t2 or
                                     (from_b2 and self.t1_bytes == self.target_t2))
            if choose_t1 or not self.t2:
                if not self.t1:
                    break
                key, size = self.t1.popitem(last=False)
                self.t1_bytes -= size
                self._remember(self.b1, key, size)
            else:
                key, size = self.t2.popitem(last=False)
                self.t2_bytes -= size
                self._remember(self.b2, key, size)
            evicted.append(key)
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

        if self.capacity_bytes <= 0 or size <= 0 or size > self.capacity_bytes:
            return []

        if key in self.b1:
            self.target_t2 = min(
                self.capacity_bytes,
                self.target_t2 + self._adaptation(self.b1_bytes, self.b2_bytes, size),
            )
            self._drop_ghost(key)
            evicted = self._replace(size, False)
            self.t2[key] = size
            self.t2_bytes += size
            return evicted

        if key in self.b2:
            self.target_t2 = max(
                0,
                self.target_t2 - self._adaptation(self.b2_bytes, self.b1_bytes, size),
            )
            self._drop_ghost(key)
            evicted = self._replace(size, True)
            self.t2[key] = size
            self.t2_bytes += size
            return evicted

        evicted = self._replace(size, False)
        self.t1[key] = size
        self.t1_bytes += size
        self._trim_ghosts()
        return evicted
