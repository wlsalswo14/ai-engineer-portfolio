from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
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

    def _remove(self, key):
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
        choose_t1 = bool(self.t1) and (
            self.bytes1 > self.target
            or (from_b2 and self.bytes1 == self.target)
        )
        if choose_t1:
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

    def _adapt(self, size, b1_hit, b2_hit):
        if not (b1_hit or b2_hit):
            return
        step = max(1, self.capacity_bytes // 16)
        delta = max(step, min(self.capacity_bytes, max(1, size)))
        if b1_hit:
            self.target = min(self.capacity_bytes, self.target + delta)
        else:
            self.target = max(0, self.target - delta)

    def access(self, key: int, size: int, now: int) -> list[int]:
        requested = int(size)
        if requested <= 0:
            if key in self.t1:
                self.t1.move_to_end(key)
            elif key in self.t2:
                self.t2.move_to_end(key)
            return []

        if requested > self.capacity_bytes:
            old_size, segment = self._remove(key)
            if segment == 1:
                self._remember(self.b1, key, old_size)
                return [key]
            if segment == 2:
                self._remember(self.b2, key, old_size)
                return [key]
            self._forget(key)
            return []

        old_size, segment = self._remove(key)
        if segment is not None:
            evicted = self._make_room(requested, False)
            self.t2[key] = requested
            self.bytes2 += requested
            return evicted

        b1_hit = key in self.b1
        b2_hit = key in self.b2
        self._adapt(requested, b1_hit, b2_hit)
        self._forget(key)
        evicted = self._make_room(requested, b2_hit)
        if b1_hit or b2_hit:
            self.t2[key] = requested
            self.bytes2 += requested
        else:
            self.t1[key] = requested
            self.bytes1 += requested
        return evicted
