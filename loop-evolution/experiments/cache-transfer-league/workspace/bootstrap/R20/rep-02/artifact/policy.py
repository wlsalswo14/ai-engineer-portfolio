from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probationary = OrderedDict()
        self.protected = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0

    def _protected_limit(self):
        if self.capacity_bytes == 0:
            return 0
        return max(1, self.capacity_bytes // 2)

    def _trim_protected(self):
        limit = self._protected_limit()
        while self.protected and self.protected_bytes > limit:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probationary[key] = size

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.probationary:
            stored_size = self.probationary.pop(key)
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            self._trim_protected()
            return []

        if size <= 0 or size > self.capacity_bytes:
            return []

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            if self.probationary:
                old_key, old_size = self.probationary.popitem(last=False)
                self.used_bytes -= old_size
                evicted.append(old_key)
            elif self.protected:
                old_key, old_size = self.protected.popitem(last=False)
                self.protected_bytes -= old_size
                self.probationary[old_key] = old_size
            else:
                break

        self.probationary[key] = size
        self.used_bytes += size
        return evicted
