from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self._t1_bytes = 0
        self._t2_bytes = 0
        self._b1_bytes = 0
        self._b2_bytes = 0
        self._resident_bytes = 0
        self._target_t1_bytes = 0

    def _remove_b1(self, key):
        size = self.b1.pop(key, None)
        if size is not None:
            self._b1_bytes -= size
        return size

    def _remove_b2(self, key):
        size = self.b2.pop(key, None)
        if size is not None:
            self._b2_bytes -= size
        return size

    def _record_ghost(self, table, key, size):
        if table is self.b1:
            old = self.b1.pop(key, None)
            if old is not None:
                self._b1_bytes -= old
            old = self.b2.pop(key, None)
            if old is not None:
                self._b2_bytes -= old
            self.b1[key] = size
            self._b1_bytes += size
        else:
            old = self.b2.pop(key, None)
            if old is not None:
                self._b2_bytes -= old
            old = self.b1.pop(key, None)
            if old is not None:
                self._b1_bytes -= old
            self.b2[key] = size
            self._b2_bytes += size
        self._trim_ghosts()

    def _trim_ghosts(self):
        limit = self.capacity_bytes * 2
        while self._b1_bytes + self._b2_bytes > limit:
            if self.b1:
                _, size = self.b1.popitem(last=False)
                self._b1_bytes -= size
            elif self.b2:
                _, size = self.b2.popitem(last=False)
                self._b2_bytes -= size
            else:
                break

    def _evict_t1(self):
        key, size = self.t1.popitem(last=False)
        self._t1_bytes -= size
        self._resident_bytes -= size
        self._record_ghost(self.b1, key, size)
        return key

    def _evict_t2(self):
        key, size = self.t2.popitem(last=False)
        self._t2_bytes -= size
        self._resident_bytes -= size
        self._record_ghost(self.b2, key, size)
        return key

    def _replace(self, incoming_size, from_b2):
        evicted = []
        while self._resident_bytes + incoming_size > self.capacity_bytes:
            if self.t1 and (
                self._t1_bytes > self._target_t1_bytes
                or (from_b2 and self._t1_bytes == self._target_t1_bytes)
            ):
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
        self._t1_bytes += size
        self._resident_bytes += size

    def _insert_t2(self, key, size):
        self.t2[key] = size
        self._t2_bytes += size
        self._resident_bytes += size

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.t1:
            stored_size = self.t1.pop(key)
            self._t1_bytes -= stored_size
            self.t2[key] = stored_size
            self._t2_bytes += stored_size
            return []

        if key in self.t2:
            stored_size = self.t2.pop(key)
            self.t2[key] = stored_size
            return []

        request_size = max(0, size)
        if self.capacity_bytes == 0 or request_size > self.capacity_bytes:
            return []

        from_b2 = key in self.b2
        if from_b2:
            self._remove_b2(key)
            delta = max(1, min(self.capacity_bytes, request_size))
            self._target_t1_bytes = max(0, self._target_t1_bytes - delta)
            evicted = self._replace(request_size, True)
            self._insert_t2(key, request_size)
            return evicted

        if key in self.b1:
            self._remove_b1(key)
            delta = max(1, min(self.capacity_bytes, request_size))
            self._target_t1_bytes = min(self.capacity_bytes, self._target_t1_bytes + delta)
            evicted = self._replace(request_size, False)
            self._insert_t2(key, request_size)
            return evicted

        evicted = self._replace(request_size, False)
        self._insert_t1(key, request_size)
        return evicted
