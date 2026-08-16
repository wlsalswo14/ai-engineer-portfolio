from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probationary = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probationary = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.probationary_bytes = 0
        self.protected_bytes = 0
        self.protected_target = self.capacity_bytes // 2
        self.ghost_limit = max(32, min(8192, self.capacity_bytes // 64 + 32))

    def _remember(self, ghost, key, size):
        ghost.pop(key, None)
        ghost[key] = size
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _forget(self, key):
        self.ghost_probationary.pop(key, None)
        self.ghost_protected.pop(key, None)

    def _rebalance_protected(self):
        while self.protected and self.protected_bytes > self.protected_target:
            old_key, old_size = self.protected.popitem(last=False)
            self.protected_bytes -= old_size
            self.probationary[old_key] = old_size
            self.probationary_bytes += old_size

    def _adjust_target(self, key, size):
        quantum = max(1, self.capacity_bytes // 16)
        amount = max(quantum, min(size, self.capacity_bytes))
        if key in self.ghost_probationary:
            self.protected_target = min(
                self.capacity_bytes, self.protected_target + amount
            )
        elif key in self.ghost_protected:
            self.protected_target = max(0, self.protected_target - amount)
        self._forget(key)

    def _evict_one(self):
        if self.probationary:
            old_key, old_size = self.probationary.popitem(last=False)
            self.probationary_bytes -= old_size
            self._remember(self.ghost_probationary, old_key, old_size)
            return old_key
        if self.protected:
            old_key, old_size = self.protected.popitem(last=False)
            self.protected_bytes -= old_size
            self._remember(self.ghost_protected, old_key, old_size)
            return old_key
        return None

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.probationary:
            stored_size = self.probationary.pop(key)
            self.probationary_bytes -= stored_size
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            self._rebalance_protected()
            return []

        if self.capacity_bytes == 0 or size <= 0 or size > self.capacity_bytes:
            return []

        self._adjust_target(key, size)
        evicted = []
        while (
            self.probationary_bytes + self.protected_bytes + size
            > self.capacity_bytes
        ):
            old_key = self._evict_one()
            if old_key is None:
                break
            evicted.append(old_key)

        self.probationary[key] = size
        self.probationary_bytes += size
        return evicted
