from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.target = self.capacity // 2
        self.a1 = OrderedDict()
        self.am = OrderedDict()
        self.a1_bytes = 0
        self.am_bytes = 0
        self.resident_bytes = 0
        self.ghosts = OrderedDict()
        self.ghost_limit = max(64, min(4096, self.capacity // 64 + 16))

    def _discard_ghost(self, key):
        self.ghosts.pop(key, None)

    def _remember_ghost(self, key, segment, size):
        self.ghosts.pop(key, None)
        self.ghosts[key] = (segment, size)
        while len(self.ghosts) > self.ghost_limit:
            self.ghosts.popitem(last=False)

    def _drop_resident(self, key):
        if key in self.a1:
            size = self.a1.pop(key)
            self.a1_bytes -= size
            self.resident_bytes -= size
            return "a1", size
        if key in self.am:
            size = self.am.pop(key)
            self.am_bytes -= size
            self.resident_bytes -= size
            return "am", size
        return None

    def _evict_one(self, segment):
        if segment == "a1" and self.a1:
            key, size = self.a1.popitem(last=False)
            self.a1_bytes -= size
        elif self.am:
            key, size = self.am.popitem(last=False)
            segment = "am"
            self.am_bytes -= size
        else:
            return None
        self.resident_bytes -= size
        self._remember_ghost(key, segment, size)
        return key

    def _make_room(self, required, evicted):
        while self.resident_bytes + required > self.capacity:
            probationary_limit = self.capacity - self.target
            if self.a1 and (not self.am or self.a1_bytes >= probationary_limit):
                segment = "a1"
            else:
                segment = "am"
            key = self._evict_one(segment)
            if key is None:
                break
            evicted.append(key)

    def _insert_a1(self, key, size):
        self._discard_ghost(key)
        self.a1[key] = size
        self.a1_bytes += size
        self.resident_bytes += size

    def _insert_am(self, key, size):
        self._discard_ghost(key)
        self.am[key] = size
        self.am_bytes += size
        self.resident_bytes += size
        while self.am_bytes > self.target and len(self.am) > 1:
            old_key, old_size = self.am.popitem(last=False)
            self.am_bytes -= old_size
            self.a1[old_key] = old_size
            self.a1_bytes += old_size

    def access(self, key: int, size: int, now: int) -> list[int]:
        del now
        evicted = []
        old = self._drop_resident(key)

        if size <= 0:
            self._discard_ghost(key)
            if old is not None:
                evicted.append(key)
            return evicted

        if size > self.capacity:
            self._discard_ghost(key)
            if old is not None:
                self._remember_ghost(key, old[0], old[1])
                evicted.append(key)
            return evicted

        ghost = self.ghosts.pop(key, None)
        if ghost is not None:
            delta = max(1, min(self.capacity, max(size, ghost[1])))
            if ghost[0] == "a1":
                self.target = max(0, self.target - delta)
            else:
                self.target = min(self.capacity, self.target + delta)
            destination = "am"
        elif old is not None:
            destination = "am"
        else:
            destination = "a1"

        self._make_room(size, evicted)
        if destination == "am":
            self._insert_am(key, size)
        else:
            self._insert_a1(key, size)
        return evicted
