from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.used_bytes = 0
        self.target_protected = self.capacity_bytes // 2
        self.probation_ghost = OrderedDict()
        self.protected_ghost = OrderedDict()
        self.ghost_limit = max(64, min(4096, self.capacity_bytes // 64 + 64))

    def _remember(self, ghost, key):
        ghost.pop(key, None)
        ghost[key] = None
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _demote(self):
        while self.protected and self.protected_bytes > self.target_protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size
            self.probation_bytes += size

    def _evict_one(self):
        if self.probation and (not self.protected or self.probation_bytes > self.capacity_bytes - self.target_protected):
            queue = self.probation
            ghost = self.probation_ghost
            self.probation_bytes_name = True
        elif self.protected:
            queue = self.protected
            ghost = self.protected_ghost
            self.probation_bytes_name = False
        elif self.probation:
            queue = self.probation
            ghost = self.probation_ghost
            self.probation_bytes_name = True
        else:
            return None
        key, size = queue.popitem(last=False)
        if self.probation_bytes_name:
            self.probation_bytes -= size
        else:
            self.protected_bytes -= size
        self.used_bytes -= size
        self._remember(ghost, key)
        return key

    def _make_room(self, size):
        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            key = self._evict_one()
            if key is None:
                break
            evicted.append(key)
        return evicted

    def _hit(self, queue, key, size, promote):
        old_size = queue.pop(key)
        if queue is self.probation:
            self.probation_bytes -= old_size
        else:
            self.protected_bytes -= old_size
        self.used_bytes -= old_size
        if size > self.capacity_bytes:
            self._remember(self.probation_ghost if queue is self.probation else self.protected_ghost, key)
            return [key]
        self.probation_ghost.pop(key, None)
        self.protected_ghost.pop(key, None)
        self.used_bytes += size
        if promote:
            self.protected[key] = size
            self.protected_bytes += size
            self._demote()
        else:
            self.protected[key] = size
            self.protected_bytes += size
            self._demote()
        return []

    def access(self, key: int, size: int, now: int) -> list[int]:
        size = max(0, int(size))
        if key in self.protected:
            return self._hit(self.protected, key, size, False)
        if key in self.probation:
            return self._hit(self.probation, key, size, True)
        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []
        probation_hit = key in self.probation_ghost
        protected_hit = key in self.protected_ghost
        if probation_hit:
            self.target_protected = max(0, self.target_protected - max(1, self.capacity_bytes // 8))
        elif protected_hit:
            self.target_protected = min(self.capacity_bytes, self.target_protected + max(1, self.capacity_bytes // 8))
        self.probation_ghost.pop(key, None)
        self.protected_ghost.pop(key, None)
        evicted = self._make_room(size)
        if self.used_bytes + size > self.capacity_bytes:
            return evicted
        if probation_hit or protected_hit:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.probation[key] = size
            self.probation_bytes += size
        self.used_bytes += size
        self._demote()
        return evicted
