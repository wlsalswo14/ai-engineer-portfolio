from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.used_bytes = 0
        self.ghost_weight = 0
        self.p = 0

    @staticmethod
    def _weight(size):
        return max(1, size)

    def _pop_ghost(self, table, key):
        size = table.pop(key)
        self.ghost_weight -= self._weight(size)
        return size

    def _record_ghost(self, table, key, size):
        if key in self.b1:
            self._pop_ghost(self.b1, key)
        if key in self.b2:
            self._pop_ghost(self.b2, key)
        table[key] = size
        self.ghost_weight += self._weight(size)
        while self.ghost_weight > self.capacity_bytes and (self.b1 or self.b2):
            victim_table = self.b1 if self.b1 else self.b2
            victim_key, victim_size = victim_table.popitem(last=False)
            self.ghost_weight -= self._weight(victim_size)

    def _replace(self, incoming_size, from_b1, evicted):
        while self.used_bytes + incoming_size > self.capacity_bytes:
            t1_bytes = sum(self.t1.values())
            choose_t1 = self.t1 and (
                t1_bytes > self.p or (from_b1 and t1_bytes == self.p)
            )
            if choose_t1:
                key, size = self.t1.popitem(last=False)
                self._record_ghost(self.b1, key, size)
            elif self.t2:
                key, size = self.t2.popitem(last=False)
                self._record_ghost(self.b2, key, size)
            elif self.t1:
                key, size = self.t1.popitem(last=False)
                self._record_ghost(self.b1, key, size)
            else:
                break
            self.used_bytes -= size
            evicted.append(key)

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.t1:
            stored_size = self.t1.pop(key)
            self.t2[key] = stored_size
            return []

        if key in self.t2:
            stored_size = self.t2.pop(key)
            self.t2[key] = stored_size
            return []

        if size < 0 or size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        evicted = []

        if key in self.b1:
            b1_weight = self.ghost_weight
            delta = max(1, sum(self._weight(v) for v in self.b2.values()) // max(1, b1_weight))
            self.p = min(self.capacity_bytes, self.p + delta)
            self._pop_ghost(self.b1, key)
            self._replace(size, True, evicted)
            self.t2[key] = size
            self.used_bytes += size
            return evicted

        if key in self.b2:
            b2_weight = self.ghost_weight
            delta = max(1, sum(self._weight(v) for v in self.b1.values()) // max(1, b2_weight))
            self.p = max(0, self.p - delta)
            self._pop_ghost(self.b2, key)
            self._replace(size, False, evicted)
            self.t2[key] = size
            self.used_bytes += size
            return evicted

        self._replace(size, False, evicted)
        self.t1[key] = size
        self.used_bytes += size
        return evicted
