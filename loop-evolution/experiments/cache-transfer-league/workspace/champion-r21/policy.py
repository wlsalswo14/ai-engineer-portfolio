from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.used_bytes = 0

    def _demote_protected(self):
        target = self.capacity_bytes // 2
        while self.protected and sum(self.protected.values()) > target:
            key, size = self.protected.popitem(last=False)
            self.probation[key] = size

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

        if size > self.capacity_bytes or self.capacity_bytes == 0:
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
        self._demote_protected()
        return evicted
