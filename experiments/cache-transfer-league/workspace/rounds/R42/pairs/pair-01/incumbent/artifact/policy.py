from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.ghost_limit = 4096
        self.target_bytes = self.capacity_bytes // 2
        self.t1_bytes = 0
        self.t2_bytes = 0
        self.used_bytes = 0

    def _remember(self, ghost, key, size):
        self.b1.pop(key, None)
        self.b2.pop(key, None)
        ghost[key] = size
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _forget_ghost(self, key):
        self.b1.pop(key, None)
        self.b2.pop(key, None)

    def _evict_one(self, incoming_key):
        from_first = self.t1 and (
            self.t1_bytes > self.target_bytes
            or (incoming_key in self.b2 and self.t1_bytes == self.target_bytes)
        )
        if from_first:
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

        size = int(size)
        if size <= 0 or self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        adjustment = max(1, min(self.capacity_bytes, size))
        if key in self.b1:
            self.target_bytes = min(
                self.capacity_bytes,
                self.target_bytes + adjustment,
            )
        elif key in self.b2:
            self.target_bytes = max(0, self.target_bytes - adjustment)
        self._forget_ghost(key)

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._evict_one(key)
            if old_key is None:
                break
            evicted.append(old_key)

        self.t1[key] = size
        self.t1_bytes += size
        self.used_bytes += size
        return evicted
