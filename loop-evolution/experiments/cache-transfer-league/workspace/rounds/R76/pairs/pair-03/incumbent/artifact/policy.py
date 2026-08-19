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
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096

    def _drop_ghost(self, key):
        value = self.b1.pop(key, None)
        if value is not None:
            self.b1_bytes -= value
        value = self.b2.pop(key, None)
        if value is not None:
            self.b2_bytes -= value

    def _remember_ghost(self, key, size, kind):
        self._drop_ghost(key)
        value = max(1, int(size))
        if kind == 1:
            self.b1[key] = value
            self.b1_bytes += value
        else:
            self.b2[key] = value
            self.b2_bytes += value
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.b1_bytes + self.b2_bytes > self.ghost_limit or
               len(self.b1) + len(self.b2) > self.ghost_count_limit):
            if not self.b1:
                ghosts = self.b2
                kind = 2
            elif not self.b2:
                ghosts = self.b1
                kind = 1
            elif next(iter(self.b1.values())) <= next(iter(self.b2.values())):
                ghosts = self.b1
                kind = 1
            else:
                ghosts = self.b2
                kind = 2
            _, value = ghosts.popitem(last=False)
            if kind == 1:
                self.b1_bytes -= value
            else:
                self.b2_bytes -= value

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
        return 0

    def _replace(self, incoming, from_b2=False):
        evicted = []
        while self.used + incoming > self.capacity:
            use_t1 = bool(self.t1) and (
                self.t1_bytes > self.target or
                (from_b2 and self.t1_bytes == self.target)
            )
            if use_t1:
                victim, value = self.t1.popitem(last=False)
                self.t1_bytes -= value
                self.used -= value
                self._remember_ghost(victim, value, 1)
            elif self.t2:
                victim, value = self.t2.popitem(last=False)
                self.t2_bytes -= value
                self.used -= value
                self._remember_ghost(victim, value, 2)
            elif self.t1:
                victim, value = self.t1.popitem(last=False)
                self.t1_bytes -= value
                self.used -= value
                self._remember_ghost(victim, value, 1)
            else:
                break
            evicted.append(victim)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = int(size)

        if key in self.t1 or key in self.t2:
            self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._replace(size)
            self._drop_ghost(key)
            self.t2[key] = size
            self.t2_bytes += size
            self.used += size
            return evicted

        kind = 1 if key in self.b1 else 2 if key in self.b2 else 0
        if size <= 0 or size > self.capacity:
            if kind:
                self._drop_ghost(key)
            return []

        if kind:
            self._adjust_target(kind)
            self._drop_ghost(key)

        evicted = self._replace(size, from_b2=(kind == 2))
        if kind:
            self.t2[key] = size
            self.t2_bytes += size
        else:
            self.t1[key] = size
            self.t1_bytes += size
        self.used += size
        return evicted
