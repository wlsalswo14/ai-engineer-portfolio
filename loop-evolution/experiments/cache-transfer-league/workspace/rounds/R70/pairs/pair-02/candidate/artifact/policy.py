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
        self.ghost_bytes = 0
        self.used = 0
        self.target = self.capacity // 2
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096

    def _discard_ghost(self, key):
        value = self.b1.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value
        value = self.b2.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value

    def _remember_ghost(self, key, size, kind):
        self._discard_ghost(key)
        table = self.b1 if kind == 1 else self.b2
        value = max(0, int(size))
        table[key] = value
        self.ghost_bytes += value
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.b1) + len(self.b2) > self.ghost_count_limit):
            table = None
            if self.b1:
                table = self.b1
                key = next(iter(self.b1))
                serial = self.b1[key]
            else:
                serial = None
            if self.b2:
                key2 = next(iter(self.b2))
                value2 = self.b2[key2]
                if table is None or value2 < serial:
                    table = self.b2
            if table is None:
                break
            _, value = table.popitem(last=False)
            self.ghost_bytes -= value

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        if kind == 1:
            delta = max(1, self.b2_bytes // max(1, self._ghost_bytes(self.b1)))
            self.target = min(self.capacity, self.target + min(self.capacity, delta))
        else:
            delta = max(1, self._ghost_bytes(self.b1) // max(1, self._ghost_bytes(self.b2)))
            self.target = max(0, self.target - min(self.capacity, delta))

    def _ghost_bytes(self, table):
        return sum(table.values())

    def _remove_resident(self, key):
        value = self.t1.pop(key, None)
        if value is not None:
            size, hits = value
            self.t1_bytes -= size
            self.used -= size
            return size, hits, 1
        value = self.t2.pop(key, None)
        if value is not None:
            size, hits = value
            self.t2_bytes -= size
            self.used -= size
            return size, hits, 2
        return 0, 0, 0

    def _evict_t1(self):
        key, (size, _) = self.t1.popitem(last=False)
        self.t1_bytes -= size
        self.used -= size
        self._remember_ghost(key, size, 1)
        return key

    def _evict_t2(self):
        key, (size, _) = self.t2.popitem(last=False)
        self.t2_bytes -= size
        self.used -= size
        self._remember_ghost(key, size, 2)
        return key

    def _make_room(self, incoming, incoming_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            prefer_t1 = bool(self.t1) and (
                self.t1_bytes > self.target or
                (incoming_kind == 2 and self.t1_bytes == self.target) or
                not self.t2
            )
            if prefer_t1:
                evicted.append(self._evict_t1())
            elif self.t2:
                evicted.append(self._evict_t2())
            elif self.t1:
                evicted.append(self._evict_t1())
            else:
                break
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))

        if key in self.t1 or key in self.t2:
            _, hits, _ = self._remove_resident(key)
            self._discard_ghost(key)
            if size > self.capacity:
                return [key]
            evicted = self._make_room(size, 2)
            self.t2[key] = (size, hits + 1)
            self.t2_bytes += size
            self.used += size
            return evicted

        kind = 1 if key in self.b1 else 2 if key in self.b2 else 0
        if size > self.capacity:
            if kind:
                self._discard_ghost(key)
            return []

        if kind:
            self._adjust_target(kind)
            self._discard_ghost(key)
            evicted = self._make_room(size, kind)
            self.t2[key] = (size, 2)
            self.t2_bytes += size
        else:
            evicted = self._make_room(size, 1)
            self.t1[key] = (size, 1)
            self.t1_bytes += size
        self.used += size
        return evicted
