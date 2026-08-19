from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.t1_bytes = 0
        self.t2_bytes = 0
        self.target_bytes = 0
        self.ghost_limit = 4096

    def _remember_ghost(self, bucket, key, size):
        self.b1.pop(key, None)
        self.b2.pop(key, None)
        bucket[key] = size
        while len(bucket) > self.ghost_limit:
            bucket.popitem(last=False)

    def _discard_ghosts(self, key):
        self.b1.pop(key, None)
        self.b2.pop(key, None)

    def _first_available(self, bucket, protected):
        for key in bucket:
            if key != protected:
                return key
        return None

    def _victim(self, b2_hit, protected):
        prefer_t1 = bool(self.t1) and (
            self.t1_bytes > self.target_bytes
            or (self.t1_bytes == self.target_bytes and b2_hit)
        )
        if prefer_t1:
            key = self._first_available(self.t1, protected)
            if key is not None:
                return self.t1, key
            key = self._first_available(self.t2, protected)
            if key is not None:
                return self.t2, key
        else:
            key = self._first_available(self.t2, protected)
            if key is not None:
                return self.t2, key
            key = self._first_available(self.t1, protected)
            if key is not None:
                return self.t1, key
        return None

    def _make_room(self, needed, protected=None, b2_hit=False):
        evicted = []
        while self.t1_bytes + self.t2_bytes + needed > self.capacity_bytes:
            choice = self._victim(b2_hit, protected)
            if choice is None:
                break
            bucket, key = choice
            size = bucket.pop(key)
            if bucket is self.t1:
                self.t1_bytes -= size
                ghost = self.b1
            else:
                self.t2_bytes -= size
                ghost = self.b2
            self._remember_ghost(ghost, key, size)
            evicted.append(key)
        return evicted

    def _insert(self, bucket, key, size):
        self._discard_ghosts(key)
        bucket[key] = size
        if bucket is self.t1:
            self.t1_bytes += size
        else:
            self.t2_bytes += size

    def access(self, key: int, size: int, now: int) -> list[int]:
        if not isinstance(key, int):
            return []
        incoming = max(0, int(size))
        _ = now

        if key in self.t1:
            old_size = self.t1.pop(key)
            self.t1_bytes -= old_size
            if incoming > self.capacity_bytes:
                self._remember_ghost(self.b1, key, old_size)
                return [key]
            evicted = self._make_room(incoming)
            self._insert(self.t2, key, incoming)
            return evicted

        if key in self.t2:
            old_size = self.t2.pop(key)
            self.t2_bytes -= old_size
            if incoming > self.capacity_bytes:
                self._remember_ghost(self.b2, key, old_size)
                return [key]
            evicted = self._make_room(incoming)
            self._insert(self.t2, key, incoming)
            return evicted

        if incoming > self.capacity_bytes:
            return []

        if key in self.b1:
            ghost_size = self.b1.pop(key)
            delta = max(1, min(self.capacity_bytes, max(incoming, ghost_size)))
            self.target_bytes = min(self.capacity_bytes, self.target_bytes + delta)
            evicted = self._make_room(incoming, b2_hit=False)
            self._insert(self.t2, key, incoming)
            return evicted

        if key in self.b2:
            ghost_size = self.b2.pop(key)
            delta = max(1, min(self.capacity_bytes, max(incoming, ghost_size)))
            self.target_bytes = max(0, self.target_bytes - delta)
            evicted = self._make_room(incoming, b2_hit=True)
            self._insert(self.t2, key, incoming)
            return evicted

        evicted = self._make_room(incoming, b2_hit=False)
        self._insert(self.t1, key, incoming)
        return evicted
