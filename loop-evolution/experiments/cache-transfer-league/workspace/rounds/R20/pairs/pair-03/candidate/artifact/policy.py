from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.used_bytes = 0

    def _demote(self):
        limit = self.capacity_bytes // 2
        protected_bytes = sum(self.protected.values())
        while self.protected and protected_bytes > limit:
            key, size = self.protected.popitem(last=False)
            self.probation[key] = size
            protected_bytes -= size

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored = self.protected.pop(key)
            self.protected[key] = stored
            return []

        if key in self.probation:
            stored = self.probation.pop(key)
            self.protected[key] = stored
            self._demote()
            return []

        if self.capacity_bytes == 0 or not isinstance(size, int) or size < 0 or size > self.capacity_bytes:
            return []

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

        self.probation[key] = size
        self.used_bytes += size
        self._demote()
        return evicted
