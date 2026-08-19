from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.t1_bytes = 0
        self.t2_bytes = 0
        self.b1_bytes = 0
        self.b2_bytes = 0
        self.used_bytes = 0
        self.target_t1_bytes = 0
        self.ghost_limit = max(64, min(4096, self.capacity_bytes + 64))

    def _discard_ghost(self, table, key):
        if key not in table:
            return 0
        size = table.pop(key)
        if table is self.b1:
            self.b1_bytes -= size
        else:
            self.b2_bytes -= size
        return size

    def _remember(self, table, key, size):
        self._discard_ghost(self.b1, key)
        self._discard_ghost(self.b2, key)
        table[key] = size
        if table is self.b1:
            self.b1_bytes += size
        else:
            self.b2_bytes += size
        while len(self.b1) + len(self.b2) > self.ghost_limit:
            victim_table = self.b1 if len(self.b1) >= len(self.b2) else self.b2
            old_key, old_size = victim_table.popitem(last=False)
            if victim_table is self.b1:
                self.b1_bytes -= old_size
            else:
                self.b2_bytes -= old_size

    def _replace(self, incoming_size):
        evicted = []
        while self.used_bytes + incoming_size > self.capacity_bytes:
            if self.t1 and (self.t1_bytes > self.target_t1_bytes or not self.t2):
                old_key, old_size = self.t1.popitem(last=False)
                self.t1_bytes -= old_size
                self.used_bytes -= old_size
                self._remember(self.b1, old_key, old_size)
            elif self.t2:
                old_key, old_size = self.t2.popitem(last=False)
                self.t2_bytes -= old_size
                self.used_bytes -= old_size
                self._remember(self.b2, old_key, old_size)
            elif self.t1:
                old_key, old_size = self.t1.popitem(last=False)
                self.t1_bytes -= old_size
                self.used_bytes -= old_size
                self._remember(self.b1, old_key, old_size)
            else:
                break
            evicted.append(old_key)
        return evicted

    def _admit(self, key, size, protected):
        evicted = self._replace(size)
        if protected:
            self.t2[key] = size
            self.t2_bytes += size
        else:
            self.t1[key] = size
            self.t1_bytes += size
        self.used_bytes += size
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        size = max(0, int(size))

        if key in self.t1:
            stored_size = self.t1.pop(key)
            self.t1_bytes -= stored_size
            self.t2[key] = stored_size
            self.t2_bytes += stored_size
            return []

        if key in self.t2:
            stored_size = self.t2.pop(key)
            self.t2[key] = stored_size
            return []

        if key in self.b1:
            prior_b1 = max(1, self.b1_bytes)
            prior_b2 = self.b2_bytes
            self._discard_ghost(self.b1, key)
            self.target_t1_bytes = min(
                self.capacity_bytes,
                self.target_t1_bytes + max(1, prior_b2 // prior_b1),
            )
            if size > self.capacity_bytes or self.capacity_bytes == 0:
                return []
            return self._admit(key, size, True)

        if key in self.b2:
            prior_b1 = self.b1_bytes
            prior_b2 = max(1, self.b2_bytes)
            self._discard_ghost(self.b2, key)
            self.target_t1_bytes = max(
                0,
                self.target_t1_bytes - max(1, prior_b1 // prior_b2),
            )
            if size > self.capacity_bytes or self.capacity_bytes == 0:
                return []
            return self._admit(key, size, True)

        if size > self.capacity_bytes or self.capacity_bytes == 0:
            return []
        return self._admit(key, size, False)
