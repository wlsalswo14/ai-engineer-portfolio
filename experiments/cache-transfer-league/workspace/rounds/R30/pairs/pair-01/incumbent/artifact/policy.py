from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.target = 0
        self.used_bytes = 0
        self.t1_bytes = 0
        self.t2_bytes = 0
        self.ghost_limit = 4096

    def _remember(self, ghost, key):
        self.b1.pop(key, None)
        self.b2.pop(key, None)
        ghost[key] = None
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _drop(self, table, key):
        size = table.pop(key)
        self.used_bytes -= size
        if table is self.t1:
            self.t1_bytes -= size
        else:
            self.t2_bytes -= size
        return size

    def _evict(self, table, ghost):
        key, size = table.popitem(last=False)
        self.used_bytes -= size
        if table is self.t1:
            self.t1_bytes -= size
        else:
            self.t2_bytes -= size
        self._remember(ghost, key)
        return key

    def _make_room(self, key, size, from_b2):
        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            if self.t1 and (
                self.t1_bytes > self.target
                or (from_b2 and self.t1_bytes == self.target)
            ):
                evicted.append(self._evict(self.t1, self.b1))
            elif self.t2:
                evicted.append(self._evict(self.t2, self.b2))
            elif self.t1:
                evicted.append(self._evict(self.t1, self.b1))
            else:
                break
        return evicted

    def _insert(self, table, key, size):
        table[key] = size
        self.used_bytes += size
        if table is self.t1:
            self.t1_bytes += size
        else:
            self.t2_bytes += size

    def access(self, key: int, size: int, now: int) -> list[int]:
        if size <= 0:
            return []

        if key in self.t1:
            old_size = self._drop(self.t1, key)
            if size > self.capacity_bytes:
                return [key]
            evicted = self._make_room(key, size, False)
            self._insert(self.t2, key, size)
            return evicted

        if key in self.t2:
            self._drop(self.t2, key)
            if size > self.capacity_bytes:
                return [key]
            evicted = self._make_room(key, size, False)
            self._insert(self.t2, key, size)
            return evicted

        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        in_b1 = key in self.b1
        in_b2 = key in self.b2
        step = max(1, self.capacity_bytes // 16)
        if in_b1:
            self.target = min(
                self.capacity_bytes,
                self.target + max(step, size),
            )
        elif in_b2:
            self.target = max(
                0,
                self.target - max(step, size),
            )

        self.b1.pop(key, None)
        self.b2.pop(key, None)
        evicted = self._make_room(key, size, in_b2)
        self._insert(self.t2 if (in_b1 or in_b2) else self.t1, key, size)
        return evicted
