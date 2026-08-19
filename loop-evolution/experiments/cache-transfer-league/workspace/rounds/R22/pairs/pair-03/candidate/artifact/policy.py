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
        self.used_bytes = 0
        self.p = 0
        self.ghost_entry_limit = max(1, min(4096, self.capacity_bytes or 1))

    def _remove_ghost(self, key):
        if key in self.b1:
            size = self.b1.pop(key)
            self.b1_bytes -= size
        if key in self.b2:
            size = self.b2.pop(key)
            self.b2_bytes -= size

    def _add_ghost(self, ghost, key, size):
        self._remove_ghost(key)
        ghost[key] = size
        if ghost is self.b1:
            self.b1_bytes += size
        else:
            self.b2_bytes += size
        while (len(ghost) > self.ghost_entry_limit or
               (self.b1_bytes if ghost is self.b1 else self.b2_bytes) > self.capacity_bytes):
            old_key, old_size = ghost.popitem(last=False)
            if ghost is self.b1:
                self.b1_bytes -= old_size
            else:
                self.b2_bytes -= old_size

    def _evict_t1(self, evicted):
        key, size = self.t1.popitem(last=False)
        self.t1_bytes -= size
        self.used_bytes -= size
        evicted.append(key)
        self._add_ghost(self.b1, key, size)

    def _evict_t2(self, evicted):
        key, size = self.t2.popitem(last=False)
        self.t2_bytes -= size
        self.used_bytes -= size
        evicted.append(key)
        self._add_ghost(self.b2, key, size)

    def _replace(self, prefer_t2, evicted):
        if self.t1 and ((prefer_t2 and self.t1_bytes == self.p) or
                        self.t1_bytes > self.p):
            self._evict_t1(evicted)
        elif self.t2:
            self._evict_t2(evicted)
        elif self.t1:
            self._evict_t1(evicted)
        else:
            return False
        return True

    def _make_room(self, size, prefer_t2, evicted):
        while self.used_bytes + size > self.capacity_bytes:
            if not self._replace(prefer_t2, evicted):
                break

    def _insert_t1(self, key, size):
        self.t1[key] = size
        self.t1_bytes += size
        self.used_bytes += size

    def _insert_t2(self, key, size):
        self.t2[key] = size
        self.t2_bytes += size
        self.used_bytes += size

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

        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        evicted = []

        if key in self.b1:
            before = max(1, self.b1_bytes)
            self.p = min(self.capacity_bytes,
                         self.p + max(1, self.b2_bytes // before))
            self._remove_ghost(key)
            self._make_room(size, True, evicted)
            self._insert_t2(key, size)
            return evicted

        if key in self.b2:
            before = max(1, self.b2_bytes)
            self.p = max(0, self.p - max(1, self.b1_bytes // before))
            self._remove_ghost(key)
            self._make_room(size, True, evicted)
            self._insert_t2(key, size)
            return evicted

        self._make_room(size, False, evicted)
        self._insert_t1(key, size)
        return evicted
