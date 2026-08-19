from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self._t1_bytes = 0
        self._t2_bytes = 0
        self._b1_bytes = 0
        self._b2_bytes = 0
        self._resident_bytes = 0
        self._target = 0
        self._ghost_sequence = 0
        self._ghost_limit = 4096

    def _drop_ghost(self, key):
        if key in self.b1:
            size, _ = self.b1.pop(key)
            self._b1_bytes -= size
            return
        if key in self.b2:
            size, _ = self.b2.pop(key)
            self._b2_bytes -= size

    def _add_ghost(self, key, size, which):
        self._drop_ghost(key)
        ghost_size = max(1, size)
        self._ghost_sequence += 1
        item = (ghost_size, self._ghost_sequence)
        if which == 1:
            self.b1[key] = item
            self._b1_bytes += ghost_size
        else:
            self.b2[key] = item
            self._b2_bytes += ghost_size
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self._b1_bytes + self._b2_bytes > self.capacity or
               len(self.b1) + len(self.b2) > self._ghost_limit):
            candidates = []
            if self.b1:
                key = next(iter(self.b1))
                candidates.append((self.b1[key][1], 1, key))
            if self.b2:
                key = next(iter(self.b2))
                candidates.append((self.b2[key][1], 2, key))
            if not candidates:
                break
            _, _, key = min(candidates)
            self._drop_ghost(key)

    def _evict_one(self, prefer_t1, evicted):
        if prefer_t1 and self.t1:
            key, size = self.t1.popitem(last=False)
            self._t1_bytes -= size
            self._resident_bytes -= size
            self._add_ghost(key, size, 1)
            evicted.append(key)
            return True
        if self.t2:
            key, size = self.t2.popitem(last=False)
            self._t2_bytes -= size
            self._resident_bytes -= size
            self._add_ghost(key, size, 2)
            evicted.append(key)
            return True
        if self.t1:
            key, size = self.t1.popitem(last=False)
            self._t1_bytes -= size
            self._resident_bytes -= size
            self._add_ghost(key, size, 1)
            evicted.append(key)
            return True
        return False

    def _make_room(self, key, size, evicted, from_b2=False):
        while self._resident_bytes + size > self.capacity:
            prefer_t1 = self._t1_bytes > self._target
            if from_b2 and self._t1_bytes == self._target:
                prefer_t1 = True
            if not self._evict_one(prefer_t1, evicted):
                break

    def _adapt_up(self, size):
        if self.capacity == 0:
            return
        delta = max(1, size)
        if self._b1_bytes:
            delta = max(delta, (self._b2_bytes * max(1, size)) // self._b1_bytes)
        self._target = min(self.capacity, self._target + min(self.capacity, delta))

    def _adapt_down(self, size):
        if self.capacity == 0:
            return
        delta = max(1, size)
        if self._b2_bytes:
            delta = max(delta, (self._b1_bytes * max(1, size)) // self._b2_bytes)
        self._target = max(0, self._target - min(self.capacity, delta))

    def _admit_recent(self, key, size):
        self.t1[key] = size
        self._t1_bytes += size
        self._resident_bytes += size

    def _admit_frequent(self, key, size):
        self.t2[key] = size
        self._t2_bytes += size
        self._resident_bytes += size

    def access(self, key: int, size: int, now: int) -> list[int]:
        size = max(0, int(size))
        evicted = []

        if key in self.t1:
            old_size = self.t1.pop(key)
            self._t1_bytes -= old_size
            self._resident_bytes -= old_size
            if size > self.capacity:
                evicted.append(key)
                return evicted
            self._make_room(key, size, evicted)
            self._admit_frequent(key, size)
            self._trim_ghosts()
            return evicted

        if key in self.t2:
            old_size = self.t2.pop(key)
            self._t2_bytes -= old_size
            self._resident_bytes -= old_size
            if size > self.capacity:
                evicted.append(key)
                return evicted
            self._make_room(key, size, evicted)
            self._admit_frequent(key, size)
            self._trim_ghosts()
            return evicted

        if size > self.capacity:
            self._drop_ghost(key)
            return evicted

        if key in self.b1:
            self._adapt_up(size)
            self._drop_ghost(key)
            self._make_room(key, size, evicted)
            self._admit_frequent(key, size)
        elif key in self.b2:
            self._adapt_down(size)
            self._drop_ghost(key)
            self._make_room(key, size, evicted, from_b2=True)
            self._admit_frequent(key, size)
        else:
            self._make_room(key, size, evicted)
            self._admit_recent(key, size)

        self._trim_ghosts()
        return evicted
