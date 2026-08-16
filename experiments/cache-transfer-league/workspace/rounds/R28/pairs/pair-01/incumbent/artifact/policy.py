from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.recent = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.ghost_limit = 4096
        self.frequency = OrderedDict()
        self.frequency_limit = 8192
        self.recent_bytes = 0
        self.protected_bytes = 0
        self.used_bytes = 0
        self.protected_target = self.capacity_bytes // 2

    def _remember(self, ghost, key):
        ghost.pop(key, None)
        ghost[key] = None
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _forget_ghost(self, key):
        self.ghost_recent.pop(key, None)
        self.ghost_protected.pop(key, None)

    def _record(self, key):
        count = self.frequency.pop(key, 0) + 1
        self.frequency[key] = min(count, 255)
        while len(self.frequency) > self.frequency_limit:
            self.frequency.popitem(last=False)

    def _rebalance(self):
        while self.protected and self.protected_bytes > self.protected_target:
            old_key, old_size = self.protected.popitem(last=False)
            self.protected_bytes -= old_size
            self.recent[old_key] = old_size
            self.recent_bytes += old_size

    def _evict_one(self):
        recent_target = self.capacity_bytes - self.protected_target
        if self.recent and (self.recent_bytes > recent_target or not self.protected):
            old_key, old_size = self.recent.popitem(last=False)
            self.recent_bytes -= old_size
            self._remember(self.ghost_recent, old_key)
        elif self.protected:
            old_key, old_size = self.protected.popitem(last=False)
            self.protected_bytes -= old_size
            self._remember(self.ghost_protected, old_key)
        else:
            return None
        self.used_bytes -= old_size
        return old_key

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

        in_recent_ghost = key in self.ghost_recent
        in_protected_ghost = key in self.ghost_protected
        if in_recent_ghost:
            delta = max(1, self.capacity_bytes // 16, min(size, self.capacity_bytes))
            self.protected_target = min(self.capacity_bytes, self.protected_target + delta)
        elif in_protected_ghost:
            delta = max(1, self.capacity_bytes // 16, min(size, self.capacity_bytes))
            self.protected_target = max(0, self.protected_target - delta)
        self._forget_ghost(key)

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._evict_one()
            if old_key is None:
                return evicted
            evicted.append(old_key)

        if in_recent_ghost or in_protected_ghost or self.frequency.get(key, 0) >= 2:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.recent[key] = size
            self.recent_bytes += size
        self.used_bytes += size
        self._rebalance()
        return evicted
