from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.protected_target = self.capacity_bytes // 2

    def _rebalance(self):
        while self.frequent and self.frequent_bytes > self.protected_target:
            key, size = self.frequent.popitem(last=False)
            self.frequent_bytes -= size
            self.recent[key] = size
            self.recent_bytes += size

    def _evict_one(self):
        if self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            return key
        if self.frequent:
            key, size = self.frequent.popitem(last=False)
            self.frequent_bytes -= size
            return key
        return None

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.frequent:
            stored_size = self.frequent.pop(key)
            self.frequent[key] = stored_size
            return []

        if key in self.recent:
            stored_size = self.recent.pop(key)
            self.recent_bytes -= stored_size
            self.frequent[key] = stored_size
            self.frequent_bytes += stored_size
            step = max(1, self.capacity_bytes // 32)
            self.protected_target = min(
                self.capacity_bytes, self.protected_target + step
            )
            self._rebalance()
            return []

        if self.capacity_bytes == 0 or size < 0 or size > self.capacity_bytes:
            return []

        step = max(1, self.capacity_bytes // 64)
        self.protected_target = max(
            self.capacity_bytes // 4, self.protected_target - step
        )
        self._rebalance()

        evicted = []
        while self.recent_bytes + self.frequent_bytes + size > self.capacity_bytes:
            old_key = self._evict_one()
            if old_key is None:
                break
            evicted.append(old_key)

        self.recent[key] = size
        self.recent_bytes += size
        self._rebalance()
        return evicted
