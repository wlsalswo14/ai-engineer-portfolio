from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probationary = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.probationary_bytes = 0
        self.protected_bytes = 0
        self.target_bytes = self.capacity_bytes // 2
        self.ghost_limit = 4096

    def _forget_ghost(self, key):
        self.ghost_recent.pop(key, None)
        self.ghost_frequent.pop(key, None)

    def _remember_ghost(self, ghost, key, size):
        self._forget_ghost(key)
        ghost[key] = size
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _take_current(self, key):
        if key in self.probationary:
            size = self.probationary.pop(key)
            self.probationary_bytes -= size
            return size, 1
        if key in self.protected:
            size = self.protected.pop(key)
            self.protected_bytes -= size
            return size, 2
        return None, None

    def _evict_one(self, frequent_hit):
        take_probationary = bool(self.probationary) and (
            not self.protected
            or self.probationary_bytes > self.target_bytes
            or (frequent_hit and self.probationary_bytes == self.target_bytes)
        )
        if take_probationary:
            key, size = self.probationary.popitem(last=False)
            self.probationary_bytes -= size
            self._remember_ghost(self.ghost_recent, key, size)
            return key
        if self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self._remember_ghost(self.ghost_frequent, key, size)
            return key
        if self.probationary:
            key, size = self.probationary.popitem(last=False)
            self.probationary_bytes -= size
            self._remember_ghost(self.ghost_recent, key, size)
            return key
        return None

    def _make_room(self, size, frequent_hit):
        evicted = []
        while self.probationary_bytes + self.protected_bytes + size > self.capacity_bytes:
            key = self._evict_one(frequent_hit)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        requested = int(size)
        _ = now

        if requested <= 0:
            if key in self.probationary:
                self.probationary.move_to_end(key)
            elif key in self.protected:
                self.protected.move_to_end(key)
            return []

        if requested > self.capacity_bytes:
            old_size, segment = self._take_current(key)
            if segment == 1:
                self._remember_ghost(self.ghost_recent, key, old_size)
                return [key]
            if segment == 2:
                self._remember_ghost(self.ghost_frequent, key, old_size)
                return [key]
            return []

        if key in self.probationary:
            self._take_current(key)
            evicted = self._make_room(requested, False)
            self.protected[key] = requested
            self.protected_bytes += requested
            return evicted

        if key in self.protected:
            self._take_current(key)
            evicted = self._make_room(requested, False)
            self.protected[key] = requested
            self.protected_bytes += requested
            return evicted

        recent_hit = key in self.ghost_recent
        frequent_hit = key in self.ghost_frequent
        if recent_hit:
            delta = max(1, min(self.capacity_bytes, max(requested, self.capacity_bytes // 16)))
            self.target_bytes = min(self.capacity_bytes, self.target_bytes + delta)
        elif frequent_hit:
            delta = max(1, min(self.capacity_bytes, max(requested, self.capacity_bytes // 16)))
            self.target_bytes = max(0, self.target_bytes - delta)

        self._forget_ghost(key)
        evicted = self._make_room(requested, frequent_hit)
        self.probationary[key] = requested
        self.probationary_bytes += requested
        return evicted
