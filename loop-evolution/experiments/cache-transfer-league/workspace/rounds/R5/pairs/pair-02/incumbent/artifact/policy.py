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
        self.target_t1_bytes = 0

    def _add_ghost(self, target, key, size):
        if key in self.b1:
            self.b1_bytes -= self.b1.pop(key)
        if key in self.b2:
            self.b2_bytes -= self.b2.pop(key)
        target[key] = size
        if target is self.b1:
            self.b1_bytes += size
        else:
            self.b2_bytes += size
        self._trim_ghosts()

    def _trim_ghosts(self):
        while self.b1_bytes + self.b2_bytes > self.capacity_bytes:
            if self.b1 and (not self.b2 or self.b1_bytes >= self.b2_bytes):
                _, size = self.b1.popitem(last=False)
                self.b1_bytes -= size
            elif self.b2:
                _, size = self.b2.popitem(last=False)
                self.b2_bytes -= size
            else:
                break

    def _replace(self, incoming_size):
        evicted = []
        while self.used_bytes + incoming_size > self.capacity_bytes:
            if self.t1 and (self.t1_bytes > self.target_t1_bytes or not self.t2):
                old_key, old_size = self.t1.popitem(last=False)
                self.t1_bytes -= old_size
                self.used_bytes -= old_size
                self._add_ghost(self.b1, old_key, old_size)
            elif self.t2:
                old_key, old_size = self.t2.popitem(last=False)
                self.t2_bytes -= old_size
                self.used_bytes -= old_size
                self._add_ghost(self.b2, old_key, old_size)
            elif self.t1:
                old_key, old_size = self.t1.popitem(last=False)
                self.t1_bytes -= old_size
                self.used_bytes -= old_size
                self._add_ghost(self.b1, old_key, old_size)
            else:
                break
            evicted.append(old_key)
        return evicted

    def _increase_target(self):
        if self.capacity_bytes:
            delta = max(1, self.b2_bytes // max(1, self.b1_bytes))
            self.target_t1_bytes = min(
                self.capacity_bytes, self.target_t1_bytes + delta
            )

    def _decrease_target(self):
        if self.capacity_bytes:
            delta = max(1, self.b1_bytes // max(1, self.b2_bytes))
            self.target_t1_bytes = max(0, self.target_t1_bytes - delta)

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
            self._increase_target()
            ghost_size = self.b1.pop(key)
            self.b1_bytes -= ghost_size
            evicted = self._replace(size)
            self.t2[key] = size
            self.t2_bytes += size
            self.used_bytes += size
            return evicted

        if key in self.b2:
            self._decrease_target()
            ghost_size = self.b2.pop(key)
            self.b2_bytes -= ghost_size
            evicted = self._replace(size)
            self.t2[key] = size
            self.t2_bytes += size
            self.used_bytes += size
            return evicted

        evicted = self._replace(size)
        self.t1[key] = size
        self.t1_bytes += size
        self.used_bytes += size
        return evicted
