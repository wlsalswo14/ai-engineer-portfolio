from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        self.capacity = max(0, int(capacity_bytes))
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.t1_bytes = 0
        self.t2_bytes = 0
        self.b1_bytes = 0
        self.b2_bytes = 0
        self.ghost_bytes = 0
        self.used = 0
        self.target = self.capacity // 2
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096
        self.serial = 0

    def _discard_ghost(self, key):
        value = self.b1.pop(key, None)
        if value is not None:
            self.b1_bytes -= value[0]
            self.ghost_bytes -= value[0]
        value = self.b2.pop(key, None)
        if value is not None:
            self.b2_bytes -= value[0]
            self.ghost_bytes -= value[0]

    def _add_ghost(self, key, size, kind):
        self._discard_ghost(key)
        self.serial += 1
        value = (max(1, int(size)), self.serial)
        if kind == 1:
            self.b1[key] = value
            self.b1_bytes += value[0]
        else:
            self.b2[key] = value
            self.b2_bytes += value[0]
        self.ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.b1) + len(self.b2) > self.ghost_count_limit):
            if self.b1 and self.b2:
                first_b1 = next(iter(self.b1.values()))
                first_b2 = next(iter(self.b2.values()))
                source = self.b1 if first_b1[1] <= first_b2[1] else self.b2
            elif self.b1:
                source = self.b1
            else:
                source = self.b2
            value = source.popitem(last=False)[1]
            self.ghost_bytes -= value[0]
            if source is self.b1:
                self.b1_bytes -= value[0]
            else:
                self.b2_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        if kind == 1:
            if self.b1_bytes == 0:
                delta = self.capacity
            else:
                delta = max(1, min(self.capacity, self.b2_bytes // self.b1_bytes or 1))
            self.target = min(self.capacity, self.target + delta)
        else:
            if self.b2_bytes == 0:
                delta = self.capacity
            else:
                delta = max(1, min(self.capacity, self.b1_bytes // self.b2_bytes or 1))
            self.target = max(0, self.target - delta)

    def _remove_resident(self, key):
        value = self.t1.pop(key, None)
        if value is not None:
            self.t1_bytes -= value
            self.used -= value
            return value
        value = self.t2.pop(key, None)
        if value is not None:
            self.t2_bytes -= value
            self.used -= value
            return value
        return None

    def _evict_one(self, prefer_t1):
        if prefer_t1 and self.t1:
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self.used -= size
            self._add_ghost(key, size, 1)
            return key
        if self.t2:
            key, size = self.t2.popitem(last=False)
            self.t2_bytes -= size
            self.used -= size
            self._add_ghost(key, size, 2)
            return key
        if self.t1:
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self.used -= size
            self._add_ghost(key, size, 1)
            return key
        return None

    def _make_room(self, incoming, ghost_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            prefer_t1 = self.t1_bytes > self.target
            if ghost_kind == 1 and self.t1_bytes >= self.target:
                prefer_t1 = True
            elif ghost_kind == 2 and self.t1_bytes == self.target:
                prefer_t1 = False
            key = self._evict_one(prefer_t1)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key, size, now):
        key = int(key)
        size = max(0, int(size))

        if key in self.t1 or key in self.t2:
            self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            if self.used + size > self.capacity:
                return evicted + [key]
            self._discard_ghost(key)
            self.t2[key] = size
            self.t2_bytes += size
            self.used += size
            return evicted

        ghost_kind = 1 if key in self.b1 else 2 if key in self.b2 else 0
        if size <= 0 or size > self.capacity:
            return []
        if ghost_kind:
            self._adjust_target(ghost_kind)
            self._discard_ghost(key)

        evicted = self._make_room(size, ghost_kind)
        if self.used + size > self.capacity:
            return evicted
        if ghost_kind:
            self.t2[key] = size
            self.t2_bytes += size
        else:
            self.t1[key] = size
            self.t1_bytes += size
        self.used += size
        return evicted
