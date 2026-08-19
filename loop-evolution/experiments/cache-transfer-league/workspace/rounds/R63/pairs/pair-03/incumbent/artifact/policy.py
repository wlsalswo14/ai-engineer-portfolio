from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.a1 = OrderedDict()
        self.am = OrderedDict()
        self.g1 = OrderedDict()
        self.g2 = OrderedDict()
        self.bytes_a1 = 0
        self.bytes_am = 0
        self.bytes_g1 = 0
        self.bytes_g2 = 0
        self.target = self.capacity_bytes // 2
        self.ghost_limit = 4096

    def _forget_ghost(self, key):
        size = self.g1.pop(key, None)
        if size is not None:
            self.bytes_g1 -= size
        size = self.g2.pop(key, None)
        if size is not None:
            self.bytes_g2 -= size

    def _remember(self, ghost, key, size):
        self._forget_ghost(key)
        ghost[key] = size
        if ghost is self.g1:
            self.bytes_g1 += size
        else:
            self.bytes_g2 += size
        while (len(self.g1) + len(self.g2) > self.ghost_limit
               or self.bytes_g1 + self.bytes_g2 > 2 * self.capacity_bytes):
            if self.g1:
                _, old_size = self.g1.popitem(last=False)
                self.bytes_g1 -= old_size
            elif self.g2:
                _, old_size = self.g2.popitem(last=False)
                self.bytes_g2 -= old_size
            else:
                break

    def _take(self, key):
        size = self.a1.pop(key, None)
        if size is not None:
            self.bytes_a1 -= size
            return size, 1
        size = self.am.pop(key, None)
        if size is not None:
            self.bytes_am -= size
            return size, 2
        return None, None

    def _evict_one(self, prefer_a1):
        use_a1 = bool(self.a1) and (
            self.bytes_a1 > self.target
            or (prefer_a1 and self.bytes_a1 == self.target)
        )
        if use_a1:
            key, size = self.a1.popitem(last=False)
            self.bytes_a1 -= size
            self._remember(self.g1, key, size)
            return key
        if self.am:
            key, size = self.am.popitem(last=False)
            self.bytes_am -= size
            self._remember(self.g2, key, size)
            return key
        if self.a1:
            key, size = self.a1.popitem(last=False)
            self.bytes_a1 -= size
            self._remember(self.g1, key, size)
            return key
        return None

    def _make_room(self, size, prefer_a1):
        evicted = []
        while self.bytes_a1 + self.bytes_am + size > self.capacity_bytes:
            key = self._evict_one(prefer_a1)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        requested = int(size)

        if requested <= 0:
            if key in self.a1:
                self.a1.move_to_end(key)
            elif key in self.am:
                self.am.move_to_end(key)
            return []

        if requested > self.capacity_bytes:
            old_size, segment = self._take(key)
            if segment == 1:
                self._remember(self.g1, key, old_size)
                return [key]
            if segment == 2:
                self._remember(self.g2, key, old_size)
                return [key]
            return []

        old_size, segment = self._take(key)
        if segment is not None:
            evicted = self._make_room(requested, False)
            self.am[key] = requested
            self.bytes_am += requested
            return evicted

        in_g1 = key in self.g1
        in_g2 = key in self.g2
        if in_g1:
            self.target = min(
                self.capacity_bytes,
                self.target + max(1, min(requested, self.capacity_bytes)),
            )
        elif in_g2:
            self.target = max(
                0,
                self.target - max(1, min(requested, self.capacity_bytes)),
            )

        self._forget_ghost(key)
        evicted = self._make_room(requested, in_g1)
        if in_g1 or in_g2:
            self.am[key] = requested
            self.bytes_am += requested
        else:
            self.a1[key] = requested
            self.bytes_a1 += requested
        return evicted
