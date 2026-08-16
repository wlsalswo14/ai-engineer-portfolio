from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.probation_bytes = 0
        self.protected_bytes = 0

    def _demote_protected(self):
        target = self.capacity_bytes // 2
        while self.protected and self.protected_bytes > target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size
            self.probation_bytes += size

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.probation_bytes -= stored_size
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            self._demote_protected()
            return []

        if size < 0 or size > self.capacity_bytes:
            return []

        evicted = []
        used = self.probation_bytes + self.protected_bytes
        while used + size > self.capacity_bytes:
            if self.probation:
                old_key, old_size = self.probation.popitem(last=False)
                self.probation_bytes -= old_size
            elif self.protected:
                old_key, old_size = self.protected.popitem(last=False)
                self.protected_bytes -= old_size
            else:
                break
            used -= old_size
            evicted.append(old_key)

        if used + size <= self.capacity_bytes:
            self.probation[key] = size
            self.probation_bytes += size

        return evicted
