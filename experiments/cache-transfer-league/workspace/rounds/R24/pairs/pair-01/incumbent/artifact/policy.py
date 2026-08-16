from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self._t1_bytes = 0
        self._t2_bytes = 0
        self._b1_bytes = 0
        self._b2_bytes = 0
        self._used_bytes = 0
        self._target_t1_bytes = self.capacity_bytes // 2
        self._ghost_limit_bytes = max(1, self.capacity_bytes * 2)
        self._ghost_limit_entries = 4096

    def _remove_ghost(self, key):
        if key in self.b1:
            size = self.b1.pop(key)
            self._b1_bytes -= size
            return
        if key in self.b2:
            size = self.b2.pop(key)
            self._b2_bytes -= size

    def _record_ghost(self, table, key, size):
        self._remove_ghost(key)
        table[key] = size
        if table is self.b1:
            self._b1_bytes += size
        else:
            self._b2_bytes += size
        while (self._b1_bytes + self._b2_bytes > self._ghost_limit_bytes or
               len(self.b1) + len(self.b2) > self._ghost_limit_entries):
            if self.b1:
                _, old_size = self.b1.popitem(last=False)
                self._b1_bytes -= old_size
            elif self.b2:
                _, old_size = self.b2.popitem(last=False)
                self._b2_bytes -= old_size
            else:
                break

    def _evict_one(self, from_b2):
        use_t1 = bool(self.t1) and (
            not self.t2 or
            self._t1_bytes > self._target_t1_bytes or
            (from_b2 and self._t1_bytes == self._target_t1_bytes)
        )
        if use_t1:
            victim, size = self.t1.popitem(last=False)
            self._t1_bytes -= size
            self._record_ghost(self.b1, victim, size)
        elif self.t2:
            victim, size = self.t2.popitem(last=False)
            self._t2_bytes -= size
            self._record_ghost(self.b2, victim, size)
        elif self.t1:
            victim, size = self.t1.popitem(last=False)
            self._t1_bytes -= size
            self._record_ghost(self.b1, victim, size)
        else:
            return None
        self._used_bytes -= size
        return victim

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.t1:
            stored_size = self.t1.pop(key)
            self._t1_bytes -= stored_size
            self.t2[key] = stored_size
            self._t2_bytes += stored_size
            return []

        if key in self.t2:
            stored_size = self.t2.pop(key)
            self.t2[key] = stored_size
            return []

        requested_size = max(0, int(size))
        if self.capacity_bytes == 0 or requested_size > self.capacity_bytes:
            return []

        in_b1 = key in self.b1
        in_b2 = key in self.b2
        if in_b1:
            self._remove_ghost(key)
            delta = max(1, self._b2_bytes // max(1, self._b1_bytes))
            self._target_t1_bytes = min(
                self.capacity_bytes,
                self._target_t1_bytes + delta,
            )
        elif in_b2:
            self._remove_ghost(key)
            delta = max(1, self._b1_bytes // max(1, self._b2_bytes))
            self._target_t1_bytes = max(0, self._target_t1_bytes - delta)

        evicted = []
        while self._used_bytes + requested_size > self.capacity_bytes:
            victim = self._evict_one(in_b2)
            if victim is None:
                break
            evicted.append(victim)

        self.t2[key] = requested_size
        self._t2_bytes += requested_size
        self._used_bytes += requested_size
        return evicted
