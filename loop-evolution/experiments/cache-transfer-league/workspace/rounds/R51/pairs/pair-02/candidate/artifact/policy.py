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
        self.target_t1 = self.capacity_bytes // 2
        self.ghost_limit = 4096

    def _remember(self, ghost, key, size):
        ghost.pop(key, None)
        ghost[key] = size
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _replace(self, from_b2):
        if self.t1 and (self.t1_bytes > self.target_t1 or (self.t1_bytes == self.target_t1 and not from_b2)):
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

    def _adapt(self, in_b1, ghost_size):
        if self.capacity_bytes <= 0:
            return
        step = max(1, min(self.capacity_bytes, ghost_size or 1))
        if in_b1:
            self.target_t1 = min(self.capacity_bytes, self.target_t1 + step)
        else:
            self.target_t1 = max(0, self.target_t1 - step)

    def _trim_ghosts(self):
        while len(self.b1) + len(self.b2) > self.ghost_limit:
            if self.b1 and (not self.b2 or len(self.b1) >= len(self.b2)):
                self.b1.popitem(last=False)
            elif self.b2:
                self.b2.popitem(last=False)
            else:
                break

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.t1:
            stored = self.t1.pop(key)
            self.t1_bytes -= stored
            self.t2[key] = stored
            self.t2_bytes += stored
            return []

        if key in self.t2:
            stored = self.t2.pop(key)
            self.t2[key] = stored
            return []

        if size <= 0 or size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        in_b1 = key in self.b1
        in_b2 = key in self.b2
        ghost_size = self.b1.get(key, self.b2.get(key, size))
        if in_b1 or in_b2:
            self._adapt(in_b1, ghost_size)
            self.b1.pop(key, None)
            self.b2.pop(key, None)

        evicted = []
        while self.t1_bytes + self.t2_bytes + size > self.capacity_bytes:
            old_key = self._replace(in_b2)
            if old_key is None:
                break
            evicted.append(old_key)

        if in_b2:
            self.t2[key] = size
            self.t2_bytes += size
        else:
            self.t1[key] = size
            self.t1_bytes += size

        self._trim_ghosts()
        return evicted
