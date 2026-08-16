from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.t1_bytes = 0
        self.t2_bytes = 0
        self.b1_bytes = 0
        self.b2_bytes = 0
        self.target_t1_bytes = 0

    def _remove_ghost(self, which, key):
        table = self.b1 if which == 1 else self.b2
        if key not in table:
            return None
        value = table.pop(key)
        if which == 1:
            self.b1_bytes -= value
        else:
            self.b2_bytes -= value
        return value

    def _remember(self, which, key, size):
        self._remove_ghost(1, key)
        self._remove_ghost(2, key)
        table = self.b1 if which == 1 else self.b2
        table[key] = size
        if which == 1:
            self.b1_bytes += size
        else:
            self.b2_bytes += size
        limit = self.capacity_bytes * 2
        while self.b1_bytes + self.b2_bytes > limit:
            if self.b1_bytes >= self.b2_bytes and self.b1:
                _, old_size = self.b1.popitem(last=False)
                self.b1_bytes -= old_size
            elif self.b2:
                _, old_size = self.b2.popitem(last=False)
                self.b2_bytes -= old_size
            elif self.b1:
                _, old_size = self.b1.popitem(last=False)
                self.b1_bytes -= old_size
            else:
                break

    def _replace_one(self, from_b2):
        if self.t1 and (self.t1_bytes > self.target_t1_bytes or
                         (from_b2 and self.t1_bytes == self.target_t1_bytes)):
            old_key, old_size = self.t1.popitem(last=False)
            self.t1_bytes -= old_size
            self._remember(1, old_key, old_size)
            return old_key, old_size
        if self.t2:
            old_key, old_size = self.t2.popitem(last=False)
            self.t2_bytes -= old_size
            self._remember(2, old_key, old_size)
            return old_key, old_size
        if self.t1:
            old_key, old_size = self.t1.popitem(last=False)
            self.t1_bytes -= old_size
            self._remember(1, old_key, old_size)
            return old_key, old_size
        return None

    def _make_room(self, size, from_b2):
        evicted = []
        while self.t1_bytes + self.t2_bytes + size > self.capacity_bytes:
            victim = self._replace_one(from_b2)
            if victim is None:
                return None
            old_key, old_size = victim
            evicted.append(old_key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
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

        if size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        if key in self.b1:
            ghost_size = self._remove_ghost(1, key)
            self.target_t1_bytes = min(
                self.capacity_bytes,
                self.target_t1_bytes + max(1, ghost_size or size),
            )
            evicted = self._make_room(size, False)
            if evicted is None:
                return []
            self.t2[key] = size
            self.t2_bytes += size
            return evicted

        if key in self.b2:
            ghost_size = self._remove_ghost(2, key)
            self.target_t1_bytes = max(
                0,
                self.target_t1_bytes - max(1, ghost_size or size),
            )
            evicted = self._make_room(size, True)
            if evicted is None:
                return []
            self.t2[key] = size
            self.t2_bytes += size
            return evicted

        evicted = self._make_room(size, False)
        if evicted is None:
            return []
        self.t1[key] = size
        self.t1_bytes += size
        return evicted
