from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0
        self.protected_limit = (self.capacity_bytes * 2) // 3
        self.ghost_limit = 4096

    def _remember_evicted(self, key, size):
        self.ghost.pop(key, None)
        self.ghost[key] = size
        while len(self.ghost) > self.ghost_limit:
            self.ghost.popitem(last=False)

    def _demote_protected(self):
        while self.protected and self.protected_bytes > self.protected_limit:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size

    def _evict_one(self, evicted):
        if self.probation:
            key, size = self.probation.popitem(last=False)
        elif self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
        else:
            return False
        self.used_bytes -= size
        self._remember_evicted(key, size)
        evicted.append(key)
        return True

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            self._demote_protected()
            return []

        if self.capacity_bytes == 0:
            return []

        size = max(0, size)
        if size > self.capacity_bytes:
            return []

        ghost_hit = key in self.ghost
        self.ghost.pop(key, None)
        self._demote_protected()

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            if not self._evict_one(evicted):
                break

        if self.used_bytes + size > self.capacity_bytes:
            return evicted

        if ghost_hit:
            self.protected[key] = size
            self.protected_bytes += size
            self.used_bytes += size
            self._demote_protected()
        else:
            self.probation[key] = size
            self.used_bytes += size

        return evicted
