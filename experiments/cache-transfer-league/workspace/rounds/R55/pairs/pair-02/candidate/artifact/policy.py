from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self._a1 = OrderedDict()
        self._am = OrderedDict()
        self._b1 = OrderedDict()
        self._b2 = OrderedDict()
        self._entry = {}
        self._used = 0
        self._p = 0
        self._b1_bytes = 0
        self._b2_bytes = 0
        self._ghost_limit = 8192

    def _remove_ghost(self, key):
        if key in self._b1:
            self._b1_bytes -= self._b1.pop(key)
        if key in self._b2:
            self._b2_bytes -= self._b2.pop(key)

    def _add_ghost(self, which, key, size):
        self._remove_ghost(key)
        if which == 1:
            self._b1[key] = size
            self._b1_bytes += size
        else:
            self._b2[key] = size
            self._b2_bytes += size
        while len(self._b1) + len(self._b2) > self._ghost_limit:
            if self._b1:
                _, old_size = self._b1.popitem(last=False)
                self._b1_bytes -= old_size
            elif self._b2:
                _, old_size = self._b2.popitem(last=False)
                self._b2_bytes -= old_size
            else:
                break

    def _remove_resident(self, key):
        if key in self._a1:
            self._a1.pop(key)
        elif key in self._am:
            self._am.pop(key)
        else:
            return
        self._used -= self._entry.pop(key)

    def _oldest_other(self, book, skip):
        for key in book:
            if key != skip:
                return key
        return None

    def _evict_one(self, prefer_recent, skip=None):
        if prefer_recent:
            books = ((self._a1, 1), (self._am, 2))
        else:
            books = ((self._am, 2), (self._a1, 1))
        for book, which in books:
            victim = self._oldest_other(book, skip)
            if victim is not None:
                size = book.pop(victim)
                self._entry.pop(victim, None)
                self._used -= size
                self._add_ghost(which, victim, size)
                return victim
        return None

    def _make_room(self, needed, incoming_from_b2=False, skip=None):
        evicted = []
        while self._used + needed > self.capacity_bytes:
            prefer_recent = self._a1_bytes() > self._p
            if self._a1_bytes() == self._p and incoming_from_b2:
                prefer_recent = True
            victim = self._evict_one(prefer_recent, skip)
            if victim is None:
                break
            evicted.append(victim)
        return evicted

    def _a1_bytes(self):
        return sum(self._a1.values())

    def _adapt(self, from_b1, size):
        unit = max(1, size)
        if from_b1:
            delta = max(unit, (self._b2_bytes * unit) // max(1, self._b1_bytes))
            self._p = min(self.capacity_bytes, self._p + delta)
        else:
            delta = max(unit, (self._b1_bytes * unit) // max(1, self._b2_bytes))
            self._p = max(0, self._p - delta)

    def access(self, key: int, size: int, now: int) -> list[int]:
        size = max(0, int(size))
        if key in self._entry:
            old_size = self._entry[key]
            evicted = []
            if size > self.capacity_bytes:
                self._remove_resident(key)
                return [key]
            if size > old_size:
                evicted = self._make_room(size - old_size, False, key)
                if self._used + size - old_size > self.capacity_bytes:
                    self._remove_resident(key)
                    return evicted + [key]
            self._used += size - old_size
            self._entry[key] = size
            if key in self._a1:
                self._a1.pop(key)
                self._am[key] = size
            else:
                self._am.pop(key, None)
                self._am[key] = size
            return evicted

        if size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        in_b1 = key in self._b1
        in_b2 = key in self._b2
        if in_b1:
            self._adapt(True, size)
        elif in_b2:
            self._adapt(False, size)
        self._remove_ghost(key)

        evicted = self._make_room(size, in_b2)
        if self._used + size > self.capacity_bytes:
            return evicted

        self._entry[key] = size
        self._used += size
        if in_b1 or in_b2:
            self._am[key] = size
        else:
            self._a1[key] = size
        return evicted
