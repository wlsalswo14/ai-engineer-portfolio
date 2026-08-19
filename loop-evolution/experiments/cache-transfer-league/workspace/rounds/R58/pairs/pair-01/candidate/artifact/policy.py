from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.target_recent = self.capacity_bytes // 2
        self.ghost_limit = 2048

    def _forget_ghost(self, key):
        self.ghost_recent.pop(key, None)
        self.ghost_frequent.pop(key, None)

    def _remember_ghost(self, bucket, key, size):
        self._forget_ghost(key)
        bucket[key] = size
        while len(bucket) > self.ghost_limit:
            bucket.popitem(last=False)

    def _remove_resident(self, key):
        if key in self.recent:
            size = self.recent.pop(key)
            self.recent_bytes -= size
            return size, 1
        if key in self.frequent:
            size = self.frequent.pop(key)
            self.frequent_bytes -= size
            return size, 2
        return None, None

    def _evict_one(self, prefer_recent):
        choose_recent = bool(self.recent) and (
            self.recent_bytes > self.target_recent
            or (prefer_recent and self.recent_bytes == self.target_recent)
        )
        if choose_recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self._remember_ghost(self.ghost_recent, key, size)
            return key
        if self.frequent:
            key, size = self.frequent.popitem(last=False)
            self.frequent_bytes -= size
            self._remember_ghost(self.ghost_frequent, key, size)
            return key
        if self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self._remember_ghost(self.ghost_recent, key, size)
            return key
        return None

    def _make_room(self, size, prefer_recent):
        evicted = []
        while self.recent_bytes + self.frequent_bytes + size > self.capacity_bytes:
            key = self._evict_one(prefer_recent)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        requested = int(size)
        if requested <= 0:
            if key in self.recent:
                self.recent.move_to_end(key)
            elif key in self.frequent:
                self.frequent.move_to_end(key)
            return []

        if requested > self.capacity_bytes:
            old_size, segment = self._remove_resident(key)
            if segment is not None:
                self._remember_ghost(
                    self.ghost_recent if segment == 1 else self.ghost_frequent,
                    key,
                    old_size,
                )
                return [key]
            return []

        if key in self.recent:
            self._remove_resident(key)
            evicted = self._make_room(requested, False)
            self.frequent[key] = requested
            self.frequent_bytes += requested
            return evicted

        if key in self.frequent:
            self._remove_resident(key)
            evicted = self._make_room(requested, False)
            self.frequent[key] = requested
            self.frequent_bytes += requested
            return evicted

        recent_ghost_hit = key in self.ghost_recent
        frequent_ghost_hit = key in self.ghost_frequent
        delta = max(1, min(self.capacity_bytes, requested))
        if recent_ghost_hit:
            self.target_recent = min(
                self.capacity_bytes,
                self.target_recent + delta,
            )
        elif frequent_ghost_hit:
            self.target_recent = max(0, self.target_recent - delta)

        self._forget_ghost(key)
        evicted = self._make_room(requested, frequent_ghost_hit)
        if recent_ghost_hit or frequent_ghost_hit:
            self.frequent[key] = requested
            self.frequent_bytes += requested
        else:
            self.recent[key] = requested
            self.recent_bytes += requested
        return evicted
