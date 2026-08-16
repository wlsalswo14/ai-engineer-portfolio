from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.protected = OrderedDict()
        self.recent_bytes = 0
        self.protected_bytes = 0
        self.used_bytes = 0
        self.frequency = {}
        self.ticks = 0

    def _record(self, key):
        count = min(255, self.frequency.pop(key, 0) + 1)
        self.frequency[key] = count
        self.ticks += 1
        if self.ticks % 2048 == 0:
            for item in list(self.frequency):
                value = self.frequency[item] // 2
                if value:
                    self.frequency[item] = value
                else:
                    del self.frequency[item]
        if len(self.frequency) > 8192:
            for item in list(self.frequency):
                if item not in self.recent and item not in self.protected:
                    del self.frequency[item]
                    break

    def _rebalance(self):
        target = (self.capacity_bytes * 2) // 3
        while self.protected and self.protected_bytes > target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.recent[key] = size
            self.recent_bytes += size

    def access(self, key: int, size: int, now: int) -> list[int]:
        self._record(key)

        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.recent:
            stored_size = self.recent.pop(key)
            self.recent_bytes -= stored_size
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            self._rebalance()
            return []

        if self.capacity_bytes == 0 or size <= 0 or size > self.capacity_bytes:
            return []

        required = self.used_bytes + size - self.capacity_bytes
        if required > self.recent_bytes and self.frequency.get(key, 1) <= 1:
            return []

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            if self.recent:
                old_key, old_size = self.recent.popitem(last=False)
                self.recent_bytes -= old_size
            elif self.protected:
                old_key, old_size = self.protected.popitem(last=False)
                self.protected_bytes -= old_size
            else:
                break
            self.used_bytes -= old_size
            evicted.append(old_key)

        if self.used_bytes + size > self.capacity_bytes:
            return evicted

        self.recent[key] = size
        self.recent_bytes += size
        self.used_bytes += size
        self._rebalance()
        return evicted
