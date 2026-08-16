from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.t1_bytes = 0
        self.t2_bytes = 0
        self.target = self.capacity // 2
        self.ghost_limit = 4096

    def _trim_ghosts(self):
        while len(self.b1) + len(self.b2) > self.ghost_limit:
            if len(self.b1) >= len(self.b2) and self.b1:
                self.b1.popitem(last=False)
            elif self.b2:
                self.b2.popitem(last=False)
            else:
                break

    def _ghost_add(self, ghost, key, size):
        ghost.pop(key, None)
        ghost[key] = size
        self._trim_ghosts()

    def _ghost_remove(self, key):
        self.b1.pop(key, None)
        self.b2.pop(key, None)

    def _move_t1_to_t2(self, key):
        size = self.t1.pop(key)
        self.t1_bytes -= size
        self.t2[key] = size
        self.t2_bytes += size

    def _evict_one(self):
        if self.t1 and (self.t1_bytes > self.target or not self.t2):
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self._ghost_add(self.b1, key, size)
        elif self.t2:
            key, size = self.t2.popitem(last=False)
            self.t2_bytes -= size
            self._ghost_add(self.b2, key, size)
        elif self.t1:
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self._ghost_add(self.b1, key, size)
        else:
            return None
        return key, size

    def _make_room(self, size):
        evicted = []
        while self.t1_bytes + self.t2_bytes + size > self.capacity:
            removed = self._evict_one()
            if removed is None:
                break
            evicted.append(removed[0])
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.t1:
            self._move_t1_to_t2(key)
            return []

        if key in self.t2:
            stored = self.t2.pop(key)
            self.t2[key] = stored
            return []

        if size <= 0 or size > self.capacity or self.capacity == 0:
            return []

        if key in self.b1:
            old = self.b1[key]
            self.target = min(
                self.capacity,
                self.target + max(size, old, self.capacity // 32, 1),
            )
            self._ghost_remove(key)
        elif key in self.b2:
            old = self.b2[key]
            self.target = max(
                0,
                self.target - max(size, old, self.capacity // 32, 1),
            )
            self._ghost_remove(key)

        evicted = self._make_room(size)
        self.t1[key] = size
        self.t1_bytes += size
        return evicted
