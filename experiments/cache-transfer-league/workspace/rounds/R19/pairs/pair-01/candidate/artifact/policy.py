from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.used_bytes = 0
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.protected_target = self.capacity_bytes // 2
        self.adjustment_step = max(1, self.capacity_bytes // 16) if self.capacity_bytes else 1
        self.history = OrderedDict()
        self.history_limit = 1024

    def _remember(self, key, was_protected):
        self.history.pop(key, None)
        self.history[key] = was_protected
        while len(self.history) > self.history_limit:
            self.history.popitem(last=False)

    def _rebalance(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size
            self.probation_bytes += size

    def _evict_one(self):
        if self.probation:
            key, size = self.probation.popitem(last=False)
            self.probation_bytes -= size
            self._remember(key, False)
        elif self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self._remember(key, True)
        else:
            return None
        self.used_bytes -= size
        return key

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
            self._rebalance()
            return []

        if self.capacity_bytes == 0 or size < 0 or size > self.capacity_bytes:
            return []

        history_kind = self.history.pop(key, None)
        if history_kind is False:
            self.protected_target = max(0, self.protected_target - self.adjustment_step)
        elif history_kind is True:
            self.protected_target = min(self.capacity_bytes, self.protected_target + self.adjustment_step)

        self._rebalance()
        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._evict_one()
            if old_key is None:
                break
            evicted.append(old_key)

        self.probation[key] = size
        self.probation_bytes += size
        self.used_bytes += size
        return evicted
