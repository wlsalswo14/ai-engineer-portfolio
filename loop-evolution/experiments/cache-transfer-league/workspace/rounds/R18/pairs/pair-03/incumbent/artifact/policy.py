from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0
        self.protected_budget = self.capacity_bytes // 2
        self.ghost = OrderedDict()
        self.history_limit = max(32, min(2048, self.capacity_bytes + 1))

    def _remember(self, key, size, segment):
        self.ghost.pop(key, None)
        self.ghost[key] = (segment, size)
        while len(self.ghost) > self.history_limit:
            self.ghost.popitem(last=False)

    def _rebalance(self):
        while self.protected and self.protected_bytes > self.protected_budget:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size

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

        if size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        history = self.ghost.pop(key, None)
        protected_entry = False
        if history is not None:
            segment, old_size = history
            adjustment = max(1, size, old_size)
            if segment == 'protected':
                self.protected_budget = min(
                    self.capacity_bytes,
                    self.protected_budget + adjustment,
                )
                protected_entry = True
            else:
                self.protected_budget = max(
                    0,
                    self.protected_budget - adjustment,
                )

        self._rebalance()
        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            if self.probation:
                old_key, old_size = self.probation.popitem(last=False)
                segment = 'probation'
            elif self.protected:
                old_key, old_size = self.protected.popitem(last=False)
                self.protected_bytes -= old_size
                segment = 'protected'
            else:
                break
            self.used_bytes -= old_size
            evicted.append(old_key)
            self._remember(old_key, old_size, segment)

        if self.used_bytes + size <= self.capacity_bytes:
            if protected_entry:
                self.protected[key] = size
                self.protected_bytes += size
            else:
                self.probation[key] = size
            self.used_bytes += size
            self._rebalance()

        return evicted
