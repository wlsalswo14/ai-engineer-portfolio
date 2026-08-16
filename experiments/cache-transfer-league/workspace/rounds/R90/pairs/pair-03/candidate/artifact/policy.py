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
        self.used = 0
        self.target = self.capacity // 2
        self.serial = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096

    def _drop_ghost(self, key):
        value = self.b1.pop(key, None)
        if value is not None:
            self.b1_bytes -= value[0]
        value = self.b2.pop(key, None)
        if value is not None:
            self.b2_bytes -= value[0]

    def _remember_ghost(self, key, size, kind):
        self._drop_ghost(key)
        self.serial += 1
        value = (max(1, int(size)), self.serial)
        if kind == 1:
            self.b1[key] = value
            self.b1_bytes += value[0]
        else:
            self.b2[key] = value
            self.b2_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.b1_bytes + self.b2_bytes > self.ghost_limit or
               len(self.b1) + len(self.b2) > self.ghost_count_limit):
            candidate = None
            source = None
            for ghosts in (self.b1, self.b2):
                if ghosts:
                    value = next(iter(ghosts.values()))
                    if candidate is None or value[1] < candidate[1]:
                        candidate = value
                        source = ghosts
            _, value = source.popitem(last=False)
            if source is self.b1:
                self.b1_bytes -= value[0]
            else:
                self.b2_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        if kind == 1:
            delta = self.capacity if self.b1_bytes == 0 else max(1, min(self.capacity, self.b2_bytes // self.b1_bytes or 1))
            self.target = min(self.capacity, self.target + delta)
        else:
            delta = self.capacity if self.b2_bytes == 0 else max(1, min(self.capacity, self.b1_bytes // self.b2_bytes or 1))
            self.target = max(0, self.target - delta)

    def _evict_from(self, source, kind):
        key, size = source.popitem(last=False)
        if source is self.t1:
            self.t1_bytes -= size
        else:
            self.t2_bytes -= size
        self.used -= size
        self._remember_ghost(key, size, kind)
        return key

    def _make_room(self, incoming, ghost_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            choose_t1 = self.t1_bytes > self.target
            if ghost_kind == 1 and self.t1_bytes == self.target:
                choose_t1 = True
            if choose_t1 and self.t1:
                evicted.append(self._evict_from(self.t1, 1))
            elif self.t2:
                evicted.append(self._evict_from(self.t2, 2))
            elif self.t1:
                evicted.append(self._evict_from(self.t1, 1))
            else:
                break
        return evicted

    def access(self, key, size, now):
        key = int(key)
        size = max(0, int(size))

        resident = None
        if key in self.t1:
            resident = self.t1.pop(key)
            self.t1_bytes -= resident
            self.used -= resident
        elif key in self.t2:
            resident = self.t2.pop(key)
            self.t2_bytes -= resident
            self.used -= resident

        if resident is not None:
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            if self.used + size > self.capacity:
                return evicted + [key]
            self._drop_ghost(key)
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
