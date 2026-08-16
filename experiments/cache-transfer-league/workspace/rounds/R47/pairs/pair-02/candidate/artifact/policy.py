from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.ghost_limit = 4096
        self.protected_target = self.capacity_bytes // 2
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.used_bytes = 0

    def _remember(self, ghost, key):
        ghost.pop(key, None)
        ghost[key] = None
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _forget_ghost(self, key):
        self.ghost_probation.pop(key, None)
        self.ghost_protected.pop(key, None)

    def _rebalance(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size
            self.probation_bytes += size

    def _evict_one(self, from_ghost_protected=False):
        choose_probation = bool(self.probation) and (
            self.probation_bytes > self.capacity_bytes - self.protected_target
            or (
                from_ghost_protected
                and self.probation_bytes == self.capacity_bytes - self.protected_target
            )
        )

        if choose_probation or not self.protected:
            if not self.probation:
                return None
            key, size = self.probation.popitem(last=False)
            self.probation_bytes -= size
            self._remember(self.ghost_probation, key)
        else:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self._remember(self.ghost_protected, key)

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

        if size <= 0 or self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        step = max(1, self.capacity_bytes // 16)
        delta = max(step, min(size, self.capacity_bytes))
        from_ghost_probation = key in self.ghost_probation
        from_ghost_protected = key in self.ghost_protected

        if from_ghost_probation:
            self.protected_target = max(0, self.protected_target - delta)
        elif from_ghost_protected:
            self.protected_target = min(
                self.capacity_bytes, self.protected_target + delta
            )

        self._forget_ghost(key)
        self._rebalance()

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._evict_one(from_ghost_protected)
            if old_key is None:
                break
            evicted.append(old_key)

        self.probation[key] = size
        self.probation_bytes += size
        self.used_bytes += size
        return evicted
