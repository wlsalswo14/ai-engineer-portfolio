from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.used_bytes = 0
        self.protected_target = self.capacity_bytes // 2
        self.max_ghost_entries = 4096

    def _discard_ghost(self, key):
        self.ghost_recent.pop(key, None)
        self.ghost_protected.pop(key, None)

    def _remember(self, table, key):
        self._discard_ghost(key)
        table[key] = None
        while len(self.ghost_recent) + len(self.ghost_protected) > self.max_ghost_entries:
            if self.ghost_recent:
                self.ghost_recent.popitem(last=False)
            else:
                self.ghost_protected.popitem(last=False)

    def _rebalance(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size
            self.probation_bytes += size

    def _adjust_target(self, key, size):
        step = max(1, min(self.capacity_bytes, max(0, size)))
        if key in self.ghost_recent:
            self.ghost_recent.pop(key, None)
            self.protected_target = min(
                self.capacity_bytes, self.protected_target + step
            )
        elif key in self.ghost_protected:
            self.ghost_protected.pop(key, None)
            self.protected_target = max(0, self.protected_target - step)

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

        item_size = max(0, size)
        if self.capacity_bytes == 0 or item_size > self.capacity_bytes:
            return []

        self._adjust_target(key, item_size)
        self._rebalance()

        evicted = []
        while self.used_bytes + item_size > self.capacity_bytes:
            if self.probation:
                old_key, old_size = self.probation.popitem(last=False)
                self.probation_bytes -= old_size
                self._remember(self.ghost_recent, old_key)
            elif self.protected:
                old_key, old_size = self.protected.popitem(last=False)
                self.protected_bytes -= old_size
                self._remember(self.ghost_protected, old_key)
            else:
                break
            self.used_bytes -= old_size
            evicted.append(old_key)

        if self.used_bytes + item_size <= self.capacity_bytes:
            self.probation[key] = item_size
            self.probation_bytes += item_size
            self.used_bytes += item_size

        return evicted
