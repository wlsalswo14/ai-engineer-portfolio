from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self._target = 0
        self._t1 = OrderedDict()
        self._t2 = OrderedDict()
        self._b1 = OrderedDict()
        self._b2 = OrderedDict()
        self._t1_bytes = 0
        self._t2_bytes = 0
        self._resident_bytes = 0
        self._ghost_limit = 256

    def _remove_ghost(self, key):
        self._b1.pop(key, None)
        self._b2.pop(key, None)

    def _ghost_bytes(self, history):
        return sum(history.values())

    def _trim_ghosts(self):
        while len(self._b1) + len(self._b2) > self._ghost_limit:
            if self._b1 and (not self._b2 or len(self._b1) >= len(self._b2)):
                self._b1.popitem(last=False)
            elif self._b2:
                self._b2.popitem(last=False)
            else:
                break

    def _remember_ghost(self, key, size, history):
        self._remove_ghost(key)
        history[key] = max(1, int(size))
        self._trim_ghosts()

    def _remove_resident(self, key):
        if key in self._t1:
            size = self._t1.pop(key)
            self._t1_bytes -= size
            self._resident_bytes -= size
            return size, 1
        if key in self._t2:
            size = self._t2.pop(key)
            self._t2_bytes -= size
            self._resident_bytes -= size
            return size, 2
        return None, 0

    def _insert_resident(self, key, size, segment):
        self._remove_ghost(key)
        if segment == 2:
            self._t2[key] = size
            self._t2_bytes += size
        else:
            self._t1[key] = size
            self._t1_bytes += size
        self._resident_bytes += size

    def _adjust_from_b1(self, size):
        b1 = max(1, self._ghost_bytes(self._b1))
        b2 = self._ghost_bytes(self._b2)
        delta = max(1, min(self.capacity_bytes, size), b2 // b1)
        self._target = min(self.capacity_bytes, self._target + delta)

    def _adjust_from_b2(self, size):
        b2 = max(1, self._ghost_bytes(self._b2))
        b1 = self._ghost_bytes(self._b1)
        delta = max(1, min(self.capacity_bytes, size), b1 // b2)
        self._target = max(0, self._target - delta)

    def _evict_one(self):
        if self._t1 and (self._t1_bytes > self._target or not self._t2):
            key, size = self._t1.popitem(last=False)
            self._t1_bytes -= size
            self._resident_bytes -= size
            self._remember_ghost(key, size, self._b1)
            return key
        if self._t2:
            key, size = self._t2.popitem(last=False)
            self._t2_bytes -= size
            self._resident_bytes -= size
            self._remember_ghost(key, size, self._b2)
            return key
        if self._t1:
            key, size = self._t1.popitem(last=False)
            self._t1_bytes -= size
            self._resident_bytes -= size
            self._remember_ghost(key, size, self._b1)
            return key
        return None

    def _make_room(self, size):
        evicted = []
        while self._resident_bytes + size > self.capacity_bytes:
            key = self._evict_one()
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        if size <= 0:
            if key in self._t1:
                value = self._t1.pop(key)
                self._t1[key] = value
            elif key in self._t2:
                value = self._t2.pop(key)
                self._t2[key] = value
            return []

        if size > self.capacity_bytes:
            old_size, segment = self._remove_resident(key)
            if segment:
                self._remember_ghost(key, old_size, self._b1 if segment == 1 else self._b2)
                return [key]
            return []

        if key in self._t1 or key in self._t2:
            old_size, _ = self._remove_resident(key)
            evicted = self._make_room(size)
            self._insert_resident(key, size, 2)
            return evicted

        segment = 1
        if key in self._b1:
            self._adjust_from_b1(size)
            segment = 2
        elif key in self._b2:
            self._adjust_from_b2(size)
            segment = 2
        self._remove_ghost(key)
        evicted = self._make_room(size)
        self._insert_resident(key, size, segment)
        return evicted
