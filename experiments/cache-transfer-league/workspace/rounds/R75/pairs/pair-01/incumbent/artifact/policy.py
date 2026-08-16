from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.used = 0
        self.protected_target = self.capacity // 2

    def _remove(self, key):
        size = self.probation.pop(key, None)
        if size is not None:
            self.probation_bytes -= size
            self.used -= size
            return size
        size = self.protected.pop(key, None)
        if size is not None:
            self.protected_bytes -= size
            self.used -= size
            return size
        return None

    def _make_room(self, incoming):
        evicted = []
        while self.used + incoming > self.capacity:
            if self.probation:
                key, size = self.probation.popitem(last=False)
                self.probation_bytes -= size
            elif self.protected:
                key, size = self.protected.popitem(last=False)
                self.protected_bytes -= size
            else:
                break
            self.used -= size
            evicted.append(int(key))
        return evicted

    def _rebalance(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size
            self.probation_bytes += size

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))

        in_probation = key in self.probation
        in_protected = key in self.protected
        if in_probation or in_protected:
            self._remove(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size)
            if in_probation:
                self.protected[key] = size
                self.protected_bytes += size
            else:
                self.protected[key] = size
                self.protected_bytes += size
            self.used += size
            self._rebalance()
            return evicted

        if size <= 0 or size > self.capacity:
            return []

        evicted = self._make_room(size)
        self.probation[key] = size
        self.probation_bytes += size
        self.used += size
        return evicted
