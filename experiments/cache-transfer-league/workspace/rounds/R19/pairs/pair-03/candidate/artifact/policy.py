from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0
        self.protected_target = self.capacity_bytes // 2
        self.min_protected = self.capacity_bytes // 4
        self.max_protected = (self.capacity_bytes * 3) // 4
        self.adaptation_step = max(1, self.capacity_bytes // 16) if self.capacity_bytes else 1
        self.recent_ghost = OrderedDict()
        self.frequent_ghost = OrderedDict()
        self.ghost_limit = 4096

    def _remember(self, key, was_protected):
        target = self.frequent_ghost if was_protected else self.recent_ghost
        other = self.recent_ghost if was_protected else self.frequent_ghost
        other.pop(key, None)
        target.pop(key, None)
        target[key] = None
        while len(self.recent_ghost) + len(self.frequent_ghost) > self.ghost_limit:
            if self.recent_ghost:
                self.recent_ghost.popitem(last=False)
            else:
                self.frequent_ghost.popitem(last=False)

    def _rebalance_protected(self):
        while self.protected and self.protected_bytes > self.protected_target:
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
            self._rebalance_protected()
            return []

        recent_hit = key in self.recent_ghost
        frequent_hit = key in self.frequent_ghost
        self.recent_ghost.pop(key, None)
        self.frequent_ghost.pop(key, None)
        if recent_hit:
            self.protected_target = max(
                self.min_protected,
                self.protected_target - self.adaptation_step,
            )
        elif frequent_hit:
            self.protected_target = min(
                self.max_protected,
                self.protected_target + self.adaptation_step,
            )

        if self.capacity_bytes == 0 or size < 0 or size > self.capacity_bytes:
            return []

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

        self.probation[key] = size
        self.used_bytes += size
        return evicted
