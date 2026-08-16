from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.bytes1 = 0
        self.bytes2 = 0
        self.target = self.capacity_bytes // 2
        self.ghost_limit = 4096

    def _forget(self, key):
        self.b1.pop(key, None)
        self.b2.pop(key, None)

    def _remember(self, ghost, key, size):
        self._forget(key)
        ghost[key] = size
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _take(self, key):
        if key in self.t1:
            size = self.t1.pop(key)
            self.bytes1 -= size
            return size, 1
        if key in self.t2:
            size = self.t2.pop(key)
            self.bytes2 -= size
            return size, 2
        return None, None

    def _evict_one(self, from_b2):
        take_t1 = bool(self.t1) and (
            self.bytes1 > self.target
            or (from_b2 and self.bytes1 == self.target)
        )
        if take_t1:
            key, size = self.t1.popitem(last=False)
            self.bytes1 -= size
            self._remember(self.b1, key, size)
            return key
        if self.t2:
            key, size = self.t2.popitem(last=False)
            self.bytes2 -= size
            self._remember(self.b2, key, size)
            return key
        if self.t1:
            key, size = self.t1.popitem(last=False)
            self.bytes1 -= size
            self._remember(self.b1, key, size)
            return key
        return None

    def _make_room(self, size, from_b2):
        evicted = []
        while self.bytes1 + self.bytes2 + size > self.capacity_bytes:
            key = self._evict_one(from_b2)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key, size, now):
        requested = int(size)
        if requested <= 0:
            if key in self.t1:
                self.t1.move_to_end(key)
            elif key in self.t2:
                self.t2.move_to_end(key)
            return []

        if requested > self.capacity_bytes:
            old_size, segment = self._take(key)
            if segment == 1:
                self._remember(self.b1, key, old_size)
                return [key]
            if segment == 2:
                self._remember(self.b2, key, old_size)
                return [key]
            return []

        if key in self.t1 or key in self.t2:
            self._take(key)
            evicted = self._make_room(requested, False)
            self.t2[key] = requested
            self.bytes2 += requested
            return evicted

        in_b1 = key in self.b1
        in_b2 = key in self.b2
        step = max(1, self.capacity_bytes // 8)
        weight = min(requested, self.capacity_bytes)

        if in_b1:
            self.target = min(self.capacity_bytes, self.target + max(step, weight))
        elif in_b2:
            self.target = max(0, self.target - max(step, weight))

        self._forget(key)
        evicted = self._make_room(requested, in_b2)
        if in_b1 or in_b2:
            self.t2[key] = requested
            self.bytes2 += requested
        else:
            self.t1[key] = requested
            self.bytes1 += requested
        return evicted
