from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.used_bytes = 0
        self.t1_bytes = 0
        self.t2_bytes = 0
        self.target_bytes = self.capacity_bytes // 2
        self.ghost_limit = 8192
        self.step = max(1, self.capacity_bytes // 16)

    def _discard_ghosts(self, key):
        self.b1.pop(key, None)
        self.b2.pop(key, None)

    def _remember(self, table, key, size):
        other = self.b2 if table is self.b1 else self.b1
        other.pop(key, None)
        table.pop(key, None)
        table[key] = size
        while len(self.b1) + len(self.b2) > self.ghost_limit:
            if self.b1:
                self.b1.popitem(last=False)
            elif self.b2:
                self.b2.popitem(last=False)
            else:
                break

    def _replace_one(self, incoming_from_b2):
        if self.t1 and (
            self.t1_bytes > self.target_bytes
            or (incoming_from_b2 and self.t1_bytes == self.target_bytes)
        ):
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self.used_bytes -= size
            self._remember(self.b1, key, size)
            return key
        if self.t2:
            key, size = self.t2.popitem(last=False)
            self.t2_bytes -= size
            self.used_bytes -= size
            self._remember(self.b2, key, size)
            return key
        if self.t1:
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self.used_bytes -= size
            self._remember(self.b1, key, size)
            return key
        return None

    def _promote(self, key):
        size = self.t1.pop(key)
        self.t1_bytes -= size
        self.t2[key] = size
        self.t2_bytes += size

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.t1:
            self._promote(key)
            return []

        if key in self.t2:
            stored = self.t2.pop(key)
            self.t2[key] = stored
            return []

        if size <= 0 or self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        incoming_from_b2 = False
        if key in self.b1:
            remembered = self.b1.get(key, size)
            delta = max(self.step, min(self.capacity_bytes, remembered))
            self.target_bytes = min(self.capacity_bytes, self.target_bytes + delta)
            destination = self.t2
        elif key in self.b2:
            remembered = self.b2.get(key, size)
            delta = max(self.step, min(self.capacity_bytes, remembered))
            self.target_bytes = max(0, self.target_bytes - delta)
            incoming_from_b2 = True
            destination = self.t2
        else:
            destination = self.t1

        self._discard_ghosts(key)
        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            victim = self._replace_one(incoming_from_b2)
            if victim is None:
                break
            evicted.append(victim)

        if self.used_bytes + size > self.capacity_bytes:
            return evicted

        destination[key] = size
        self.used_bytes += size
        if destination is self.t1:
            self.t1_bytes += size
        else:
            self.t2_bytes += size
        return evicted
