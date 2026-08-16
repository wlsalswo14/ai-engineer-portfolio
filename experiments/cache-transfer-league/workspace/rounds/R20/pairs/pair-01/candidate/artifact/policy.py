from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0
        self.protected_target = self.capacity_bytes // 2
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.ghost_limit = 4096

    def _remember(self, key, protected):
        first = self.ghost_protected if protected else self.ghost_probation
        second = self.ghost_probation if protected else self.ghost_protected
        first.pop(key, None)
        second.pop(key, None)
        first[key] = None
        while len(first) > self.ghost_limit:
            first.popitem(last=False)

    def _rebalance(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size
            self.probation.move_to_end(key, last=False)

    def _adapt(self, key):
        if key in self.ghost_protected:
            self.ghost_protected.pop(key, None)
            step = max(1, self.capacity_bytes // 16)
            self.protected_target = min(self.capacity_bytes, self.protected_target + step)
        elif key in self.ghost_probation:
            self.ghost_probation.pop(key, None)
            step = max(1, self.capacity_bytes // 16)
            self.protected_target = max(0, self.protected_target - step)
        self._rebalance()

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            self._rebalance()
            return []

        if self.capacity_bytes == 0 or size < 0 or size > self.capacity_bytes:
            return []

        self._adapt(key)
        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            if self.probation:
                old_key, old_size = self.probation.popitem(last=False)
                self._remember(old_key, False)
            elif self.protected:
                old_key, old_size = self.protected.popitem(last=False)
                self.protected_bytes -= old_size
                self._remember(old_key, True)
            else:
                break
            self.used_bytes -= old_size
            evicted.append(old_key)

        if self.used_bytes + size <= self.capacity_bytes:
            self.probation[key] = size
            self.used_bytes += size
        return evicted
