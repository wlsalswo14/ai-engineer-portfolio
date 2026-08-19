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
        self.resident_bytes = 0
        self.p = 0
        self.history_limit = 4096

    def _trim_ghosts(self):
        while (self.b1_bytes + self.b2_bytes > self.capacity_bytes or
               len(self.b1) + len(self.b2) > self.history_limit):
            if self.b1 and (self.b1_bytes > self.p or not self.b2):
                _, size = self.b1.popitem(last=False)
                self.b1_bytes -= size
            elif self.b2:
                _, size = self.b2.popitem(last=False)
                self.b2_bytes -= size
            elif self.b1:
                _, size = self.b1.popitem(last=False)
                self.b1_bytes -= size
            else:
                break

    def _remove_ghost(self, key):
        if key in self.b1:
            self.b1_bytes -= self.b1.pop(key)
            return
        if key in self.b2:
            self.b2_bytes -= self.b2.pop(key)

    def _remember(self, key, size, from_t1):
        self._remove_ghost(key)
        if from_t1:
            self.b1[key] = size
            self.b1_bytes += size
        else:
            self.b2[key] = size
            self.b2_bytes += size
        self._trim_ghosts()

    def _evict_one(self, prefer_t1):
        if prefer_t1 and self.t1:
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self.resident_bytes -= size
            self._remember(key, size, True)
            return key
        if self.t2:
            key, size = self.t2.popitem(last=False)
            self.t2_bytes -= size
            self.resident_bytes -= size
            self._remember(key, size, False)
            return key
        if self.t1:
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self.resident_bytes -= size
            self._remember(key, size, True)
            return key
        return None

    def _make_room(self, size, from_b1):
        evicted = []
        while self.resident_bytes + size > self.capacity_bytes:
            prefer_t1 = bool(self.t1) and (
                self.t1_bytes > self.p or
                (from_b1 and self.t1_bytes == self.p)
            )
            key = self._evict_one(prefer_t1)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def _insert(self, key, size, protected):
        if protected:
            self.t2[key] = size
            self.t2_bytes += size
        else:
            self.t1[key] = size
            self.t1_bytes += size
        self.resident_bytes += size

    def access(self, key: int, size: int, now: int) -> list[int]:
        del now
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

        size = max(0, int(size))
        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        if key in self.b1:
            ghost_size = self.b1.pop(key)
            self.b1_bytes -= ghost_size
            self.p = min(self.capacity_bytes,
                         self.p + max(1, min(self.capacity_bytes, ghost_size)))
            evicted = self._make_room(size, True)
            self._insert(key, size, True)
            return evicted

        if key in self.b2:
            ghost_size = self.b2.pop(key)
            self.b2_bytes -= ghost_size
            self.p = max(0,
                         self.p - max(1, min(self.capacity_bytes, ghost_size)))
            evicted = self._make_room(size, False)
            self._insert(key, size, True)
            return evicted

        evicted = self._make_room(size, False)
        self._insert(key, size, False)
        return evicted
