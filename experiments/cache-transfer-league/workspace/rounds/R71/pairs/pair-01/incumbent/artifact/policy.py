from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.t1_bytes = 0
        self.t2_bytes = 0
        self.resident_bytes = 0
        self.p = 0
        self.ghost_limit = 4096
        self.item_limit = 8192

    def _remember_ghost(self, ghost, key):
        self.b1.pop(key, None)
        self.b2.pop(key, None)
        ghost[key] = None
        while len(self.b1) + len(self.b2) > self.ghost_limit:
            if self.b1 and (len(self.b1) >= len(self.b2) or not self.b2):
                self.b1.popitem(last=False)
            elif self.b2:
                self.b2.popitem(last=False)
            else:
                break

    def _discard_ghost(self, key):
        self.b1.pop(key, None)
        self.b2.pop(key, None)

    def _evict_lru(self, use_t1):
        region = self.t1 if use_t1 else self.t2
        if not region:
            region = self.t2 if use_t1 else self.t1
            use_t1 = not use_t1
        if not region:
            return None
        key, value = region.popitem(last=False)
        if use_t1:
            self.t1_bytes -= value
            self._remember_ghost(self.b1, key)
        else:
            self.t2_bytes -= value
            self._remember_ghost(self.b2, key)
        self.resident_bytes -= value
        return key

    def _replace_one(self, prefer_t2=False):
        if self.t1 and (self.t1_bytes > self.p or (self.t1_bytes == self.p and prefer_t2)):
            return self._evict_lru(True)
        if self.t2:
            return self._evict_lru(False)
        if self.t1:
            return self._evict_lru(True)
        return None

    def _make_room(self, incoming, prefer_t2=False):
        evicted = []
        while (self.resident_bytes + incoming > self.capacity or
               len(self.t1) + len(self.t2) >= self.item_limit):
            key = self._replace_one(prefer_t2)
            if key is None:
                break
            if key not in evicted:
                evicted.append(key)
        return evicted

    def _adjust_target(self, in_b1, in_b2):
        step = max(1, self.capacity // 8)
        if in_b1:
            self.p = min(self.capacity, self.p + step)
        elif in_b2:
            self.p = max(0, self.p - step)

    def access(self, key: int, size: int, now: int) -> list[int]:
        value = max(0, int(size))
        evicted = []

        if key in self.t1:
            old = self.t1.pop(key)
            self.t1_bytes -= old
            self.resident_bytes -= old
            if value <= 0 or value > self.capacity:
                self._remember_ghost(self.b1, key)
                return [key]
            self.t2[key] = value
            self.t2_bytes += value
            self.resident_bytes += value
            evicted.extend(self._make_room(0))
            return evicted

        if key in self.t2:
            old = self.t2.pop(key)
            self.t2_bytes -= old
            self.resident_bytes -= old
            if value <= 0 or value > self.capacity:
                self._remember_ghost(self.b2, key)
                return [key]
            self.t2[key] = value
            self.t2_bytes += value
            self.resident_bytes += value
            evicted.extend(self._make_room(0))
            return evicted

        if value <= 0 or value > self.capacity:
            return []

        in_b1 = key in self.b1
        in_b2 = key in self.b2
        self._adjust_target(in_b1, in_b2)
        self._discard_ghost(key)
        evicted.extend(self._make_room(value, in_b2))

        if in_b1 or in_b2:
            self.t2[key] = value
            self.t2_bytes += value
        else:
            self.t1[key] = value
            self.t1_bytes += value
        self.resident_bytes += value
        return evicted
