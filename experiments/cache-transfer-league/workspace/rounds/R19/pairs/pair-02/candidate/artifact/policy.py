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
        self.target_t1_bytes = self.capacity_bytes // 2

    def _drop_ghost(self, key):
        if key in self.b1:
            self.b1_bytes -= self.b1.pop(key)
            return 'b1'
        if key in self.b2:
            self.b2_bytes -= self.b2.pop(key)
            return 'b2'
        return None

    def _remember(self, ghost, key, size):
        if size <= 0:
            return
        other = self.b2 if ghost == self.b1 else self.b1
        if key in other:
            if ghost is self.b1:
                self.b2_bytes -= other.pop(key)
            else:
                self.b1_bytes -= other.pop(key)
        if key in ghost:
            if ghost is self.b1:
                self.b1_bytes -= ghost.pop(key)
            else:
                self.b2_bytes -= ghost.pop(key)
        ghost[key] = size
        if ghost is self.b1:
            self.b1_bytes += size
        else:
            self.b2_bytes += size
        limit = 2 * self.capacity_bytes
        while self.b1_bytes + self.b2_bytes > limit:
            if self.b1_bytes >= self.b2_bytes and self.b1:
                _, old_size = self.b1.popitem(last=False)
                self.b1_bytes -= old_size
            elif self.b2:
                _, old_size = self.b2.popitem(last=False)
                self.b2_bytes -= old_size
            else:
                break

    def _replace(self, ghost_kind):
        choose_t1 = self.t1 and (
            self.t1_bytes > self.target_t1_bytes
            or (ghost_kind == 'b2' and self.t1_bytes == self.target_t1_bytes)
        )
        if choose_t1 or not self.t2:
            if not self.t1:
                return None
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self._remember(self.b1, key, size)
            return key
        key, size = self.t2.popitem(last=False)
        self.t2_bytes -= size
        self._remember(self.b2, key, size)
        return key

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

        size = max(0, int(size))
        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        ghost_kind = self._drop_ghost(key)
        if ghost_kind == 'b1':
            delta = max(size, 1)
            self.target_t1_bytes = min(
                self.capacity_bytes, self.target_t1_bytes + delta
            )
        elif ghost_kind == 'b2':
            delta = max(size, 1)
            self.target_t1_bytes = max(0, self.target_t1_bytes - delta)

        evicted = []
        while self.t1_bytes + self.t2_bytes + size > self.capacity_bytes:
            old_key = self._replace(ghost_kind)
            if old_key is None:
                break
            evicted.append(old_key)

        self.t2[key] = size if ghost_kind else size
        self.t2_bytes += size if ghost_kind else 0
        if ghost_kind is None:
            self.t2.pop(key)
            self.t1[key] = size
            self.t1_bytes += size
        return evicted
