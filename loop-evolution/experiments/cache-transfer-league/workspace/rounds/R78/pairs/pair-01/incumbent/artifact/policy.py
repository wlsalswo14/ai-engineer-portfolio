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

    def _remember_ghost(self, key, size, kind):
        if self.capacity <= 0:
            return
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
            kind = 1
            oldest = None
            if self.b1:
                oldest = next(iter(self.b1.values()))[1]
            if self.b2:
                other = next(iter(self.b2.values()))[1]
                if oldest is None or other < oldest:
                    kind = 2
            ghosts = self.b1 if kind == 1 else self.b2
            _, value = ghosts.popitem(last=False)
            if kind == 1:
                self.b1_bytes -= value[0]
            else:
                self.b2_bytes -= value[0]
            self.ghost_bytes -= value[0]

    def _adapt(self, kind):
        if self.capacity <= 0:
            return
        if kind == 1:
            delta = (self.capacity if self.b1_bytes == 0 else
                     max(1, min(self.capacity, self.b2_bytes // self.b1_bytes or 1)))
            self.target = min(self.capacity, self.target + delta)
        else:
            delta = (self.capacity if self.b2_bytes == 0 else
                     max(1, min(self.capacity, self.b1_bytes // self.b2_bytes or 1)))
            self.target = max(0, self.target - delta)

    def _replace(self, incoming, ghost_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            choose_t1 = bool(self.t1) and (
                self.t1_bytes > self.target or
                (ghost_kind == 2 and self.t1_bytes >= self.target)
            )
            if choose_t1:
                key, size = self.t1.popitem(last=False)
                self.t1_bytes -= size
                self.used -= size
                self._remember_ghost(key, size, 1)
                evicted.append(key)
            elif self.t2:
                key, size = self.t2.popitem(last=False)
                self.t2_bytes -= size
                self.used -= size
                self._remember_ghost(key, size, 2)
                evicted.append(key)
            elif self.t1:
                key, size = self.t1.popitem(last=False)
                self.t1_bytes -= size
                self.used -= size
                self._remember_ghost(key, size, 1)
                evicted.append(key)
            else:
                break
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))

        if key in self.t1:
            old = self.t1.pop(key)
            self.t1_bytes -= old
            self.used -= old
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._replace(size, 0)
            self.t2[key] = size
            self.t2_bytes += size
            self.used += size
            return evicted

        if key in self.t2:
            old = self.t2.pop(key)
            self.t2_bytes -= old
            self.used -= old
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._replace(size, 0)
            self.t2[key] = size
            self.t2_bytes += size
            self.used += size
            return evicted

        ghost_kind = 1 if key in self.b1 else 2 if key in self.b2 else 0
        if size <= 0 or size > self.capacity:
            self._discard_ghost(key)
            return []

        if ghost_kind:
            self._adapt(ghost_kind)
            self._discard_ghost(key)

        evicted = self._replace(size, ghost_kind)
        if ghost_kind:
            self.t2[key] = size
            self.t2_bytes += size
        else:
            self.t1[key] = size
            self.t1_bytes += size
        self.used += size
        return evicted
