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
        self.target_t1_bytes = self.capacity_bytes // 2
        self.used_bytes = 0
        self.ghost_limit = 8192
        self.ghost_byte_limit = max(4096, self.capacity_bytes * 2)

    def _discard_ghost(self, key):
        if key in self.b1:
            self.b1_bytes -= self.b1.pop(key)
        if key in self.b2:
            self.b2_bytes -= self.b2.pop(key)

    def _record_ghost(self, table, key, size):
        self._discard_ghost(key)
        table[key] = size
        if table is self.b1:
            self.b1_bytes += size
        else:
            self.b2_bytes += size
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (len(self.b1) + len(self.b2) > self.ghost_limit or
               self.b1_bytes + self.b2_bytes > self.ghost_byte_limit):
            if self.b1 and (not self.b2 or self.b1_bytes >= self.b2_bytes):
                _, size = self.b1.popitem(last=False)
                self.b1_bytes -= size
            elif self.b2:
                _, size = self.b2.popitem(last=False)
                self.b2_bytes -= size
            else:
                break

    def _evict_t1(self):
        key, size = self.t1.popitem(last=False)
        self.t1_bytes -= size
        self.used_bytes -= size
        self._record_ghost(self.b1, key, size)
        return key

    def _evict_t2(self):
        key, size = self.t2.popitem(last=False)
        self.t2_bytes -= size
        self.used_bytes -= size
        self._record_ghost(self.b2, key, size)
        return key

    def _replace(self, incoming: int, from_b2: bool = False):
        evicted = []
        while self.used_bytes + incoming > self.capacity_bytes:
            if self.t1 and (self.t1_bytes > self.target_t1_bytes or
                            (from_b2 and self.t1_bytes == self.target_t1_bytes)):
                evicted.append(self._evict_t1())
            elif self.t2:
                evicted.append(self._evict_t2())
            elif self.t1:
                evicted.append(self._evict_t1())
            else:
                break
        return evicted

    def _insert_t1(self, key, size):
        self.t1[key] = size
        self.t1_bytes += size
        self.used_bytes += size

    def _insert_t2(self, key, size):
        self.t2[key] = size
        self.t2_bytes += size
        self.used_bytes += size

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

        incoming = max(0, int(size))
        if self.capacity_bytes == 0 or incoming == 0 or incoming > self.capacity_bytes:
            return []

        from_b2 = key in self.b2
        if key in self.b1:
            b1_bytes = max(1, self.b1_bytes)
            delta = max(1, self.b2_bytes // b1_bytes)
            self.target_t1_bytes = min(self.capacity_bytes,
                                       self.target_t1_bytes + delta)
            self._discard_ghost(key)
            evicted = self._replace(incoming)
            self._insert_t2(key, incoming)
            return evicted

        if from_b2:
            b2_bytes = max(1, self.b2_bytes)
            delta = max(1, self.b1_bytes // b2_bytes)
            self.target_t1_bytes = max(0, self.target_t1_bytes - delta)
            self._discard_ghost(key)
            evicted = self._replace(incoming, True)
            self._insert_t2(key, incoming)
            return evicted

        evicted = self._replace(incoming)
        self._insert_t1(key, incoming)
        return evicted
