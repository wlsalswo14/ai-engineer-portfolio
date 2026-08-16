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
        self.target_bytes = 0

    def _remove_ghost(self, key):
        if key in self.b1:
            size = self.b1.pop(key)
            self.ghost_bytes -= size
            return
        if key in self.b2:
            size = self.b2.pop(key)
            self.ghost_bytes -= size

    def _trim_ghosts(self):
        while self.ghost_bytes > self.capacity_bytes:
            if self.b1:
                _, size = self.b1.popitem(last=False)
            elif self.b2:
                _, size = self.b2.popitem(last=False)
            else:
                self.ghost_bytes = 0
                break
            self.ghost_bytes -= size

    def _add_ghost(self, target, key, size):
        self._remove_ghost(key)
        target[key] = size
        self.ghost_bytes += size
        self._trim_ghosts()

    def _replace(self, incoming_size: int, from_b2: bool):
        evicted = []
        while self.t1_bytes + self.t2_bytes + incoming_size > self.capacity_bytes:
            use_t1 = bool(self.t1) and (
                self.t1_bytes > self.target_bytes
                or (from_b2 and self.t1_bytes == self.target_bytes)
            )
            if use_t1 or not self.t2:
                old_key, old_size = self.t1.popitem(last=False)
                self.t1_bytes -= old_size
                self._add_ghost(self.b1, old_key, old_size)
            elif self.t2:
                old_key, old_size = self.t2.popitem(last=False)
                self.t2_bytes -= old_size
                self._add_ghost(self.b2, old_key, old_size)
            else:
                break
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
            self.t2.move_to_end(key)
            return []

        if self.capacity_bytes == 0 or size <= 0 or size > self.capacity_bytes:
            return []

        from_b2 = key in self.b2
        if key in self.b1:
            self.target_bytes = min(
                self.capacity_bytes, self.target_bytes + size
            )
            self._remove_ghost(key)
        elif from_b2:
            self.target_bytes = max(0, self.target_bytes - size)
            self._remove_ghost(key)

        evicted = self._replace(size, from_b2)
        if self.t1_bytes + self.t2_bytes + size > self.capacity_bytes:
            return evicted

        if from_b2 or key in self.b1:
            self.t2[key] = size
            self.t2_bytes += size
        else:
            self.t1[key] = size
            self.t1_bytes += size
        return evicted
