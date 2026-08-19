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
        self.used_bytes = 0
        self.target_t1_bytes = self.capacity_bytes // 2
        self.ghost_limit = 4096

    def _drop_ghost(self, key):
        self.b1.pop(key, None)
        self.b2.pop(key, None)

    def _remember(self, ghost, key):
        self._drop_ghost(key)
        ghost[key] = None
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _evict_one(self):
        if self.t1 and (self.t1_bytes > self.target_t1_bytes or not self.t2):
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self._remember(self.b1, key)
        elif self.t2:
            key, size = self.t2.popitem(last=False)
            self.t2_bytes -= size
            self._remember(self.b2, key)
        elif self.t1:
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self._remember(self.b1, key)
        else:
            return None
        self.used_bytes -= size
        return key

    def _insert(self, key, size, protected):
        if protected:
            self.t2[key] = size
            self.t2_bytes += size
        else:
            self.t1[key] = size
            self.t1_bytes += size
        self.used_bytes += size

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.t2:
            stored_size = self.t2.pop(key)
            self.t2[key] = stored_size
            return []

        if key in self.t1:
            stored_size = self.t1.pop(key)
            self.t1_bytes -= stored_size
            self.t2[key] = stored_size
            self.t2_bytes += stored_size
            return []

        if self.capacity_bytes == 0 or size <= 0 or size > self.capacity_bytes:
            return []

        in_b1 = key in self.b1
        in_b2 = key in self.b2
        if in_b1:
            self.target_t1_bytes = min(
                self.capacity_bytes,
                self.target_t1_bytes + max(1, min(size, self.capacity_bytes)),
            )
        elif in_b2:
            self.target_t1_bytes = max(
                0,
                self.target_t1_bytes - max(1, min(size, self.capacity_bytes)),
            )
        self._drop_ghost(key)

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._evict_one()
            if old_key is None:
                break
            evicted.append(old_key)

        self._insert(key, size, in_b1 or in_b2)
        return evicted
