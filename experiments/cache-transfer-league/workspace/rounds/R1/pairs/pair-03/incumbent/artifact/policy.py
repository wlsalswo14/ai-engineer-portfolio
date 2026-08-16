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
        self.p_bytes = self.capacity_bytes // 2

    def _forget_ghost(self, book, key):
        if key in book:
            size = book.pop(key)
            self.ghost_bytes -= size
            return size
        return None

    def _remember(self, book, key, size):
        self._forget_ghost(self.b1, key)
        self._forget_ghost(self.b2, key)
        book[key] = size
        self.ghost_bytes += size
        while self.ghost_bytes > 2 * self.capacity_bytes:
            if self.b1:
                _, old_size = self.b1.popitem(last=False)
            elif self.b2:
                _, old_size = self.b2.popitem(last=False)
            else:
                break
            self.ghost_bytes -= old_size

    def _replace(self, incoming_size, prefer_t1, evicted):
        while self.t1_bytes + self.t2_bytes + incoming_size > self.capacity_bytes:
            choose_t1 = self.t1 and (
                self.t1_bytes > self.p_bytes
                or (prefer_t1 and self.t1_bytes == self.p_bytes)
                or not self.t2
            )
            if choose_t1:
                old_key, old_size = self.t1.popitem(last=False)
                self.t1_bytes -= old_size
                self._remember(self.b1, old_key, old_size)
            elif self.t2:
                old_key, old_size = self.t2.popitem(last=False)
                self.t2_bytes -= old_size
                self._remember(self.b2, old_key, old_size)
            elif self.t1:
                old_key, old_size = self.t1.popitem(last=False)
                self.t1_bytes -= old_size
                self._remember(self.b1, old_key, old_size)
            else:
                break
            evicted.append(old_key)

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

        evicted = []
        if key in self.b1:
            self._forget_ghost(self.b1, key)
            self.p_bytes = min(self.capacity_bytes, self.p_bytes + max(1, size))
            self._replace(size, False, evicted)
            self.t2[key] = size
            self.t2_bytes += size
            return evicted

        if key in self.b2:
            self._forget_ghost(self.b2, key)
            self.p_bytes = max(0, self.p_bytes - max(1, size))
            self._replace(size, True, evicted)
            self.t2[key] = size
            self.t2_bytes += size
            return evicted

        self._replace(size, False, evicted)
        self.t1[key] = size
        self.t1_bytes += size
        return evicted
