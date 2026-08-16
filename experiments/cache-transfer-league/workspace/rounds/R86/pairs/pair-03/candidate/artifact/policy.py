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
        self.used = 0
        self.target = self.capacity // 2
        self.ghost_bytes = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096
        self.serial = 0

    def _drop_ghost(self, key):
        value = self.b1.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]
        value = self.b2.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, kind):
        self._drop_ghost(key)
        self.serial += 1
        value = (max(1, int(size)), self.serial)
        if kind == 1:
            self.b1[key] = value
        else:
            self.b2[key] = value
        self.ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while self.ghost_bytes > self.ghost_limit or len(self.b1) + len(self.b2) > self.ghost_count_limit:
            if self.b1 and (not self.b2 or next(iter(self.b1.values()))[1] <= next(iter(self.b2.values()))[1]):
                source = self.b1
            else:
                source = self.b2
            _, value = source.popitem(last=False)
            self.ghost_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        b1 = sum(value[0] for value in self.b1.values())
        b2 = sum(value[0] for value in self.b2.values())
        if kind == 1:
            delta = self.capacity if b1 == 0 else max(1, min(self.capacity, b2 // b1 or 1))
            self.target = min(self.capacity, self.target + delta)
        else:
            delta = self.capacity if b2 == 0 else max(1, min(self.capacity, b1 // b2 or 1))
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

    def _replace(self, ghost_kind):
        if self.t1 and ((ghost_kind == 2 and self.t1_bytes == self.target) or self.t1_bytes > self.target):
            source = self.t1
            kind = 1
        elif self.t2:
            source = self.t2
            kind = 2
        elif self.t1:
            source = self.t1
            kind = 1
        else:
            return None
        key, size = source.popitem(last=False)
        if kind == 1:
            self.t1_bytes -= size
        else:
            self.t2_bytes -= size
        self.used -= size
        self._remember_ghost(key, size, kind)
        return key

    def _make_room(self, incoming, ghost_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            key = self._replace(ghost_kind)
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
            self.t2[key] = size
            self.t2_bytes += size
            self.used += size
            return evicted

        ghost_kind = 1 if key in self.b1 else 2 if key in self.b2 else 0
        if size <= 0 or size > self.capacity:
            return []
        if ghost_kind:
            self._adjust_target(ghost_kind)
            self._drop_ghost(key)

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
