from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost = OrderedDict()
        self.used_bytes = 0
        self.resident_high_water = 0

    def _remember_eviction(self, key):
        self.ghost.pop(key, None)
        self.ghost[key] = None
        limit = max(1, self.resident_high_water)
        while len(self.ghost) > limit:
            self.ghost.popitem(last=False)

    def _demote_protected(self):
        target = self.capacity_bytes // 2
        protected_bytes = sum(self.protected.values())
        while self.protected and protected_bytes > target:
            key, size = self.protected.popitem(last=False)
            self.probation[key] = size
            protected_bytes -= size

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.protected[key] = stored_size
            self._demote_protected()
            return []

        if size < 0 or size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        promote = key in self.ghost
        self.ghost.pop(key, None)
        evicted = []

        while self.used_bytes + size > self.capacity_bytes:
            if self.probation:
                old_key, old_size = self.probation.popitem(last=False)
            elif self.protected:
                old_key, old_size = self.protected.popitem(last=False)
            else:
                break
            self.used_bytes -= old_size
            evicted.append(old_key)
            self._remember_eviction(old_key)

        if promote:
            self.protected[key] = size
        else:
            self.probation[key] = size
        self.used_bytes += size
        self.resident_high_water = max(
            self.resident_high_water,
            len(self.probation) + len(self.protected),
        )
        self._demote_protected()
        return evicted
