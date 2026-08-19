from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.target = self.capacity_bytes // 2
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.bytes1 = 0
        self.bytes2 = 0
        self.ghost_limit = 4096

    def _forget_ghost(self, key):
        self.b1.pop(key, None)
        self.b2.pop(key, None)

    def _remember(self, ghost, key, size):
        self._forget_ghost(key)
        ghost[key] = int(size)
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

    def _evict_one(self, b2_hit):
        use_t1 = bool(self.t1) and (
            self.bytes1 > self.target
            or (b2_hit and self.bytes1 == self.target)
        )
        if use_t1:
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

    def _make_room(self, size, b2_hit):
        evicted = []
        while self.bytes1 + self.bytes2 + size > self.capacity_bytes:
            key = self._evict_one(b2_hit)
            if key is None:
                break
            evicted.append(int(key))
        return evicted

    def _adjust_target(self, b1_hit, b2_hit, requested):
        if self.capacity_bytes <= 0:
            self.target = 0
            return
        if b1_hit:
            if len(self.b1) >= len(self.b2):
                delta = requested
            else:
                delta = requested * len(self.b2) // max(1, len(self.b1))
            self.target = min(self.capacity_bytes, self.target + max(1, delta))
        elif b2_hit:
            if len(self.b2) >= len(self.b1):
                delta = requested
            else:
                delta = requested * len(self.b1) // max(1, len(self.b2))
            self.target = max(0, self.target - max(1, delta))

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
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

        old_size, segment = self._take(key)
        if segment is not None:
            self._forget_ghost(key)
            evicted = self._make_room(requested, False)
            self.t2[key] = requested
            self.bytes2 += requested
            return evicted

        b1_hit = key in self.b1
        b2_hit = key in self.b2
        self._adjust_target(b1_hit, b2_hit, requested)
        self._forget_ghost(key)
        evicted = self._make_room(requested, b2_hit)

        if b1_hit or b2_hit:
            self.t2[key] = requested
            self.bytes2 += requested
        else:
            self.t1[key] = requested
            self.bytes1 += requested
        return evicted
