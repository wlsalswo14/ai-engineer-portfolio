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
        self.target_t1 = self.capacity_bytes // 2
        self.ghost_capacity = self.capacity_bytes * 2

    def _remove_ghost(self, key):
        if key in self.b1:
            size = self.b1.pop(key)
            self.b1_bytes -= size
            return size
        if key in self.b2:
            size = self.b2.pop(key)
            self.b2_bytes -= size
            return size
        return None

    def _remember(self, ghost, key, size):
        self._remove_ghost(key)
        if self.ghost_capacity <= 0:
            return
        ghost[key] = size
        if ghost is self.b1:
            self.b1_bytes += size
        else:
            self.b2_bytes += size
        while self.b1_bytes + self.b2_bytes > self.ghost_capacity:
            if self.b1:
                old_key, old_size = self.b1.popitem(last=False)
                self.b1_bytes -= old_size
            elif self.b2:
                old_key, old_size = self.b2.popitem(last=False)
                self.b2_bytes -= old_size
            else:
                break

    def _evict_one(self):
        if self.t1 and (self.t1_bytes > self.target_t1 or not self.t2):
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self._remember(self.b1, key, size)
            return key
        if self.t2:
            key, size = self.t2.popitem(last=False)
            self.t2_bytes -= size
            self._remember(self.b2, key, size)
            return key
        if self.t1:
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self._remember(self.b1, key, size)
            return key
        return None

    def access(self, key: int, size: int, now: int) -> list[int]:
        del now

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

        if size <= 0 or size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        if key in self.b1:
            delta = max(1, min(self.capacity_bytes, size))
            self.target_t1 = min(self.capacity_bytes, self.target_t1 + delta)
            self._remove_ghost(key)
            destination = self.t2
        elif key in self.b2:
            delta = max(1, min(self.capacity_bytes, size))
            self.target_t1 = max(0, self.target_t1 - delta)
            self._remove_ghost(key)
            destination = self.t2
        else:
            destination = self.t1

        evicted = []
        while self.t1_bytes + self.t2_bytes + size > self.capacity_bytes:
            old_key = self._evict_one()
            if old_key is None:
                break
            evicted.append(old_key)

        destination[key] = size
        if destination is self.t1:
            self.t1_bytes += size
        else:
            self.t2_bytes += size
        return evicted
