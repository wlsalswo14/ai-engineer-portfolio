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
        self.ghost_limit = max(1, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096

    def _drop_ghost(self, key):
        value = self.b1.pop(key, None)
        if value is not None:
            self.b1_bytes -= value[0]
            self.ghost_bytes -= value[0]
        value = self.b2.pop(key, None)
        if value is not None:
            self.b2_bytes -= value[0]
            self.ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, kind):
        self._drop_ghost(key)
        self.serial += 1
        value = (size, self.serial)
        if kind == 1:
            self.b1[key] = value
            self.b1_bytes += size
        else:
            self.b2[key] = value
            self.b2_bytes += size
        self.ghost_bytes += size
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.b1) + len(self.b2) > self.ghost_count_limit):
            queue = self.b1
            if self.b2:
                if not self.b1 or next(iter(self.b2.values()))[1] < next(iter(self.b1.values()))[1]:
                    queue = self.b2
            _, value = queue.popitem(last=False)
            if queue is self.b1:
                self.b1_bytes -= value[0]
            else:
                self.b2_bytes -= value[0]
            self.ghost_bytes -= value[0]

    def _adjust_target(self, kind):
        if kind == 1:
            delta = self.capacity if self.b1_bytes == 0 else max(1, min(self.capacity, self.b2_bytes // self.b1_bytes))
            self.target = min(self.capacity, self.target + delta)
        else:
            delta = self.capacity if self.b2_bytes == 0 else max(1, min(self.capacity, self.b1_bytes // self.b2_bytes))
            self.target = max(0, self.target - delta)

    def _evict_one(self, incoming_kind):
        prefer_t1 = self.t1_bytes > self.target
        if incoming_kind == 2 and self.t1_bytes == self.target:
            prefer_t1 = True
        if prefer_t1 and self.t1:
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

    def _make_room(self, incoming, incoming_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            key = self._evict_one(incoming_kind)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))
        if self.capacity <= 0:
            return []

        if key in self.t1:
            old = self.t1.pop(key)
            self.t1_bytes -= old
            self.used -= old
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
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
            evicted = self._make_room(size, 0)
            self.t2[key] = size
            self.t2_bytes += size
            self.used += size
            return evicted

        ghost_kind = 1 if key in self.b1 else 2 if key in self.b2 else 0
        if size <= 0 or size > self.capacity:
            self._drop_ghost(key)
            return []

        if ghost_kind:
            self._adjust_target(ghost_kind)
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
