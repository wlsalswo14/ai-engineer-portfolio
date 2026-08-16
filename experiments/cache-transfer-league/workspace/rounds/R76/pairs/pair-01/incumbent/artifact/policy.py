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
        self.b1_bytes = 0
        self.b2_bytes = 0
        self.used = 0
        self.target = self.capacity // 2
        self._serial = 0
        self._ghost_bytes = 0
        self._ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self._ghost_count_limit = 4096

    def _remove_ghost(self, key):
        value = self.b1.pop(key, None)
        if value is not None:
            self.b1_bytes -= value[0]
            self._ghost_bytes -= value[0]
        value = self.b2.pop(key, None)
        if value is not None:
            self.b2_bytes -= value[0]
            self._ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, kind):
        self._remove_ghost(key)
        self._serial += 1
        value = (size, self._serial)
        if kind == 1:
            self.b1[key] = value
            self.b1_bytes += size
        else:
            self.b2[key] = value
            self.b2_bytes += size
        self._ghost_bytes += size
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self._ghost_bytes > self._ghost_limit or
               len(self.b1) + len(self.b2) > self._ghost_count_limit):
            oldest_kind = 0
            oldest_serial = None
            if self.b1:
                oldest_kind = 1
                oldest_serial = next(iter(self.b1.values()))[1]
            if self.b2:
                serial = next(iter(self.b2.values()))[1]
                if oldest_serial is None or serial < oldest_serial:
                    oldest_kind = 2
            ghosts = self.b1 if oldest_kind == 1 else self.b2
            _, value = ghosts.popitem(last=False)
            if oldest_kind == 1:
                self.b1_bytes -= value[0]
            else:
                self.b2_bytes -= value[0]
            self._ghost_bytes -= value[0]

    def _adapt(self, kind):
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
            return 1
        value = self.t2.pop(key, None)
        if value is not None:
            self.t2_bytes -= value
            self.used -= value
            return 2
        return 0

    def _evict_one(self, from_b1):
        choose_t1 = bool(self.t1) and (
            self.t1_bytes > self.target or
            (from_b1 and self.t1_bytes == self.target)
        )
        if choose_t1 or not self.t2:
            if self.t1:
                key, size = self.t1.popitem(last=False)
                self.t1_bytes -= size
                self.used -= size
                self._remember_ghost(key, size, 1)
                return key
        if self.t2:
            key, size = self.t2.popitem(last=False)
            self.t2_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 2)
            return key
        if self.t1:
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 1)
            return key
        return None

    def _make_room(self, incoming, from_b1):
        evicted = []
        while self.used + incoming > self.capacity:
            key = self._evict_one(from_b1)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))

        if key in self.t1 or key in self.t2:
            self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, False)
            self._remove_ghost(key)
            self.t2[key] = size
            self.t2_bytes += size
            self.used += size
            return evicted

        ghost_kind = 1 if key in self.b1 else 2 if key in self.b2 else 0
        if size <= 0 or size > self.capacity:
            return []

        if ghost_kind:
            self._adapt(ghost_kind)
            self._remove_ghost(key)

        evicted = self._make_room(size, ghost_kind == 1)
        if ghost_kind:
            self.t2[key] = size
            self.t2_bytes += size
        else:
            self.t1[key] = size
            self.t1_bytes += size
        self.used += size
        return evicted
