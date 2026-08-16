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
        self.used = 0
        self.target = self.capacity // 2
        self.ghost_bytes = 0
        self.ghost_serial = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096

    def _drop_ghost(self, key):
        for ghost in (self.b1, self.b2):
            value = ghost.pop(key, None)
            if value is not None:
                self.ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, ghost):
        self._drop_ghost(key)
        self.ghost_serial += 1
        value = (size, self.ghost_serial)
        ghost[key] = value
        self.ghost_bytes += size
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.b1) + len(self.b2) > self.ghost_count_limit):
            selected = None
            selected_serial = None
            for ghost in (self.b1, self.b2):
                if ghost:
                    serial = next(iter(ghost.values()))[1]
                    if selected_serial is None or serial < selected_serial:
                        selected = ghost
                        selected_serial = serial
            _, value = selected.popitem(last=False)
            self.ghost_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        if kind == 1:
            delta = self.capacity if not self.b1 else max(1, min(self.capacity, self.b2_bytes() // max(1, self.b1_bytes()) or 1))
            self.target = min(self.capacity, self.target + delta)
        else:
            delta = self.capacity if not self.b2 else max(1, min(self.capacity, self.b1_bytes() // max(1, self.b2_bytes()) or 1))
            self.target = max(0, self.target - delta)

    def b1_bytes(self):
        return sum(value[0] for value in self.b1.values())

    def b2_bytes(self):
        return sum(value[0] for value in self.b2.values())

    def _evict_one(self, prefer_t1):
        if prefer_t1 and self.t1:
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, self.b1)
            return key
        if self.t2:
            key, size = self.t2.popitem(last=False)
            self.t2_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, self.b2)
            return key
        if self.t1:
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, self.b1)
            return key
        return None

    def _make_room(self, incoming, ghost_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            prefer_t1 = self.t1_bytes > self.target or not self.t2
            if ghost_kind == 1 and self.t1_bytes >= self.target:
                prefer_t1 = True
            key = self._evict_one(prefer_t1)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))

        if key in self.t1:
            old_size = self.t1.pop(key)
            self.t1_bytes -= old_size
            self.used -= old_size
            self.t2[key] = old_size
            self.t2_bytes += old_size
            self.used += old_size
            return []

        if key in self.t2:
            old_size = self.t2.pop(key)
            self.t2[key] = old_size
            return []

        if size <= 0 or size > self.capacity:
            return []

        ghost_kind = 1 if key in self.b1 else 2 if key in self.b2 else 0
        if ghost_kind == 1:
            self._adjust_target(1)
            self._drop_ghost(key)
        elif ghost_kind == 2:
            self._adjust_target(2)
            self._drop_ghost(key)

        evicted = self._make_room(size, ghost_kind)
        if ghost_kind:
            self.t2[key] = size
            self.t2_bytes += size
        else:
            self.t1[key] = size
            self.t1_bytes += size
        self.used += size
        return evicted
