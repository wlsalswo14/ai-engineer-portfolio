from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.used_bytes = 0
        self.protected_target = self.capacity_bytes // 2
        self.ghost_recent = OrderedDict()
        self.ghost_protected = OrderedDict()
        if self.capacity_bytes:
            self.ghost_limit = max(16, min(4096, self.capacity_bytes // 64 + 1))
        else:
            self.ghost_limit = 0

    def _rebalance(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size
            self.probation_bytes += size

    def _remember(self, key, size, protected):
        if not self.ghost_limit:
            return
        self.ghost_recent.pop(key, None)
        self.ghost_protected.pop(key, None)
        target = self.ghost_protected if protected else self.ghost_recent
        target[key] = size
        while len(target) > self.ghost_limit:
            target.popitem(last=False)

    def _adaptation_step(self, size):
        if size > 0:
            return min(self.capacity_bytes, size)
        return max(1, self.capacity_bytes // 16)

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

        if self.capacity_bytes == 0 or size <= 0 or size > self.capacity_bytes:
            return []

        ghost_size = self.ghost_recent.pop(key, None)
        if ghost_size is not None:
            self.protected_target = max(
                0, self.protected_target - self._adaptation_step(ghost_size)
            )
        else:
            ghost_size = self.ghost_protected.pop(key, None)
            if ghost_size is not None:
                self.protected_target = min(
                    self.capacity_bytes,
                    self.protected_target + self._adaptation_step(ghost_size),
                )

        self._rebalance()
        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            if self.probation:
                old_key, old_size = self.probation.popitem(last=False)
                self.probation_bytes -= old_size
                self._remember(old_key, old_size, False)
            elif self.protected:
                old_key, old_size = self.protected.popitem(last=False)
                self.protected_bytes -= old_size
                self._remember(old_key, old_size, True)
            else:
                break
            self.used_bytes -= old_size
            evicted.append(old_key)

        self.probation[key] = size
        self.probation_bytes += size
        self.used_bytes += size
        self._rebalance()
        return evicted
