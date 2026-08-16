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
        self.ghost_bytes = 0
        self.target_bytes = self.capacity_bytes // 2

    def _discard_ghost(self, key):
        if key in self.b1:
            self.ghost_bytes -= self.b1.pop(key)
            return 1
        if key in self.b2:
            self.ghost_bytes -= self.b2.pop(key)
            return 2
        return 0

    def _record_ghost(self, which, key, size):
        self._discard_ghost(key)
        ghost = self.b1 if which == 1 else self.b2
        ghost[key] = size
        self.ghost_bytes += size
        limit = self.capacity_bytes * 2
        while ghost and self.ghost_bytes > limit:
            old_key, old_size = ghost.popitem(last=False)
            self.ghost_bytes -= old_size

    def _rebalance_protected(self):
        limit = max(0, self.capacity_bytes - self.target_bytes)
        while len(self.t2) > 1 and self.t2_bytes > limit:
            key, size = self.t2.popitem(last=False)
            self.t2_bytes -= size
            self.t1[key] = size
            self.t1_bytes += size

    def _choose_victim(self):
        if self.t1 and (self.t1_bytes > self.target_bytes or not self.t2):
            return self.t1, 1
        if self.t2:
            return self.t2, 2
        if self.t1:
            return self.t1, 1
        return None, 0

    def _make_room(self, size):
        evicted = []
        while self.t1_bytes + self.t2_bytes + size > self.capacity_bytes:
            cache, which = self._choose_victim()
            if not cache:
                break
            key, stored_size = cache.popitem(last=False)
            if which == 1:
                self.t1_bytes -= stored_size
            else:
                self.t2_bytes -= stored_size
            self._record_ghost(which, key, stored_size)
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.t1:
            stored_size = self.t1.pop(key)
            self.t1_bytes -= stored_size
            self.t2[key] = stored_size
            self.t2_bytes += stored_size
            self._rebalance_protected()
            return []

        if key in self.t2:
            stored_size = self.t2.pop(key)
            self.t2[key] = stored_size
            return []

        if size <= 0 or size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        ghost_kind = self._discard_ghost(key)
        step = min(size, self.capacity_bytes)
        if ghost_kind == 1:
            self.target_bytes = min(self.capacity_bytes, self.target_bytes + max(1, step))
        elif ghost_kind == 2:
            self.target_bytes = max(0, self.target_bytes - max(1, step))

        evicted = self._make_room(size)
        if ghost_kind:
            self.t2[key] = size
            self.t2_bytes += size
            self._rebalance_protected()
        else:
            self.t1[key] = size
            self.t1_bytes += size
        return evicted
