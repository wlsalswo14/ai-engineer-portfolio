from collections import OrderedDict


class Policy:
    _RESIDENT_LIMIT = 4096
    _GHOST_LIMIT = 4096

    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.used = 0
        self.target = 0
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()

    @staticmethod
    def _size(value):
        try:
            return max(0, int(value))
        except (TypeError, ValueError, OverflowError):
            return 0

    def _remember_ghost(self, key, size, frequent):
        self.b1.pop(key, None)
        self.b2.pop(key, None)
        target = self.b2 if frequent else self.b1
        target[key] = size
        while len(target) > self._GHOST_LIMIT:
            target.popitem(last=False)

    def _victim(self, favor_recent):
        if self.t1 and (not self.t2 or self.t1_bytes >= self.target or favor_recent):
            return self.t1, False
        if self.t2:
            return self.t2, True
        if self.t1:
            return self.t1, False
        return None, False

    def _make_room(self, incoming, evicted, favor_recent=False):
        while (self.used + incoming > self.capacity or
               len(self.t1) + len(self.t2) >= self._RESIDENT_LIMIT):
            source, frequent = self._victim(favor_recent)
            if source is None:
                break
            key, size = source.popitem(last=False)
            self.used -= size
            self._remember_ghost(key, size, frequent)
            if key not in evicted:
                evicted.append(key)

    def _install(self, key, size, frequent, evicted, favor_recent=False):
        self._make_room(size, evicted, favor_recent)
        target = self.t2 if frequent else self.t1
        target[key] = size
        self.used += size

    def _resident_hit(self, key, size):
        if key in self.t1:
            old = self.t1.pop(key)
        else:
            old = self.t2.pop(key)
        self.used -= old
        if size > self.capacity:
            return [key]
        evicted = []
        self._install(key, size, True, evicted)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        size = self._size(size)
        if key in self.t1 or key in self.t2:
            return self._resident_hit(key, size)

        in_b1 = key in self.b1
        in_b2 = key in self.b2
        if in_b1:
            old = self.b1.pop(key)
            self.target = min(self.capacity, self.target + max(1, old))
        elif in_b2:
            old = self.b2.pop(key)
            self.target = max(0, self.target - max(1, old))

        if size > self.capacity:
            return []

        evicted = []
        self._install(key, size, bool(in_b1 or in_b2), evicted, in_b2)
        return evicted

    @property
    def t1_bytes(self):
        return sum(self.t1.values())
