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
        self.serial = 0
        self.ghost_bytes = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096

    def _discard_ghost(self, key):
        value = self.b1.pop(key, None)
        if value is not None:
            self.b1_bytes -= value[0]
            self.ghost_bytes -= value[0]
        value = self.b2.pop(key, None)
        if value is not None:
            self.b2_bytes -= value[0]
            self.ghost_bytes -= value[0]

    def _remember(self, key, size, frequent):
        self._discard_ghost(key)
        self.serial += 1
        value = (size, self.serial)
        if frequent:
            self.b2[key] = value
            self.b2_bytes += size
        else:
            self.b1[key] = value
            self.b1_bytes += size
        self.ghost_bytes += size
        while (self.ghost_bytes > self.ghost_limit or
               len(self.b1) + len(self.b2) > self.ghost_count_limit):
            candidate = None
            source = None
            if self.b1:
                candidate = next(iter(self.b1.items()))
                source = self.b1
            if self.b2:
                other = next(iter(self.b2.items()))
                if candidate is None or other[1][1] < candidate[1][1]:
                    candidate = other
                    source = self.b2
            key, value = candidate
            del source[key]
            self.ghost_bytes -= value[0]
            if source is self.b1:
                self.b1_bytes -= value[0]
            else:
                self.b2_bytes -= value[0]

    def _remove_resident(self, key):
        size = self.t1.pop(key, None)
        if size is not None:
            self.t1_bytes -= size
            self.used -= size
            return size, False
        size = self.t2.pop(key, None)
        if size is not None:
            self.t2_bytes -= size
            self.used -= size
            return size, True
        return 0, False

    def _evict_t1(self):
        key, size = self.t1.popitem(last=False)
        self.t1_bytes -= size
        self.used -= size
        self._remember(key, size, False)
        return key

    def _evict_t2(self):
        key, size = self.t2.popitem(last=False)
        self.t2_bytes -= size
        self.used -= size
        self._remember(key, size, True)
        return key

    def _make_room(self, incoming, ghost_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            if self.t1 and (self.t1_bytes > self.target or
                             (ghost_kind == 2 and self.t1_bytes == self.target)):
                evicted.append(self._evict_t1())
            elif self.t2:
                evicted.append(self._evict_t2())
            elif self.t1:
                evicted.append(self._evict_t1())
            else:
                break
        return evicted

    def _adjust_target(self, kind):
        if kind == 1:
            delta = self.capacity if not self.b1_bytes else max(1, self.b2_bytes // self.b1_bytes or 1)
            self.target = min(self.capacity, self.target + delta)
        else:
            delta = self.capacity if not self.b2_bytes else max(1, self.b1_bytes // self.b2_bytes or 1)
            self.target = max(0, self.target - delta)

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))

        if key in self.t1 or key in self.t2:
            old_size, _ = self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
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
        if ghost_kind == 2:
            self.t2[key] = size
            self.t2_bytes += size
        else:
            self.t1[key] = size
            self.t1_bytes += size
        self.used += size
        return evicted
