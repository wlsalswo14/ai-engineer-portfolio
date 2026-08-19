from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self._p = 0
        self._t1 = OrderedDict()
        self._t2 = OrderedDict()
        self._b1 = OrderedDict()
        self._b2 = OrderedDict()
        self._t1_bytes = 0
        self._t2_bytes = 0
        self._b1_bytes = 0
        self._b2_bytes = 0
        self._used_bytes = 0

    def _ghost_add(self, table, key, size):
        if key in self._b1:
            self._b1_bytes -= self._b1.pop(key)
        if key in self._b2:
            self._b2_bytes -= self._b2.pop(key)
        table[key] = size
        if table is self._b1:
            self._b1_bytes += size
        else:
            self._b2_bytes += size
        limit = 2 * self.capacity_bytes
        while self._b1_bytes + self._b2_bytes > limit:
            if self._b1:
                old_key, old_size = self._b1.popitem(last=False)
                self._b1_bytes -= old_size
            elif self._b2:
                old_key, old_size = self._b2.popitem(last=False)
                self._b2_bytes -= old_size
            else:
                break

    def _remove_ghost(self, key):
        if key in self._b1:
            self._b1_bytes -= self._b1.pop(key)
            return 1
        if key in self._b2:
            self._b2_bytes -= self._b2.pop(key)
            return 2
        return 0

    def _evict(self, table, segment):
        if not table:
            return None
        key, size = table.popitem(last=False)
        if segment == 1:
            self._t1_bytes -= size
            self._ghost_add(self._b1, key, size)
        else:
            self._t2_bytes -= size
            self._ghost_add(self._b2, key, size)
        self._used_bytes -= size
        return key

    def _replace(self, favor_t1):
        if self._t1 and (self._t1_bytes > self._p or (favor_t1 and self._t1_bytes == self._p)):
            return self._evict(self._t1, 1)
        if self._t2:
            return self._evict(self._t2, 2)
        if self._t1:
            return self._evict(self._t1, 1)
        return None

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self._t1:
            stored_size = self._t1.pop(key)
            self._t1_bytes -= stored_size
            self._t2[key] = stored_size
            self._t2_bytes += stored_size
            return []

        if key in self._t2:
            stored_size = self._t2.pop(key)
            self._t2[key] = stored_size
            return []

        if self.capacity_bytes == 0 or size <= 0 or size > self.capacity_bytes:
            return []

        ghost_kind = 0
        if key in self._b1:
            ghost_kind = 1
            delta = max(1, self._b2_bytes // max(1, self._b1_bytes))
            self._p = min(self.capacity_bytes, self._p + max(size, delta))
        elif key in self._b2:
            ghost_kind = 2
            delta = max(1, self._b1_bytes // max(1, self._b2_bytes))
            self._p = max(0, self._p - max(size, delta))
        self._remove_ghost(key)

        evicted = []
        while self._used_bytes + size > self.capacity_bytes:
            victim = self._replace(ghost_kind == 2)
            if victim is None:
                break
            evicted.append(victim)

        if ghost_kind:
            self._t2[key] = size
            self._t2_bytes += size
        else:
            self._t1[key] = size
            self._t1_bytes += size
        self._used_bytes += size
        return evicted
