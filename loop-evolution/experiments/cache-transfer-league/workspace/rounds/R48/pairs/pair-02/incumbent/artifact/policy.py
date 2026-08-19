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

    def _discard_ghost(self, key):
        self.ghost_probation.pop(key, None)
        self.ghost_protected.pop(key, None)

    def _rebalance(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size
            self.probation_bytes += size

    def _evict_from_probation(self):
        key, size = self.probation.popitem(last=False)
        self.probation_bytes -= size
        self.used_bytes -= size
        self._remember(self.ghost_probation, key)
        return key

    def _evict_from_protected(self):
        key, size = self.protected.popitem(last=False)
        self.protected_bytes -= size
        self.used_bytes -= size
        self._remember(self.ghost_protected, key)
        return key

    def _replace(self, incoming_from_protected: bool):
        if self.probation and (
            self.probation_bytes > self.protected_target
            or (incoming_from_protected and self.probation_bytes == self.protected_target)
        ):
            return self._evict_from_probation()
        if self.protected:
            return self._evict_from_protected()
        if self.probation:
            return self._evict_from_probation()
        return None

    def _adapt_target(self, size: int, from_probation_ghost: bool):
        step = max(1, self.capacity_bytes // 16)
        delta = max(step, min(size, self.capacity_bytes))
        if from_probation_ghost:
            self.protected_target = min(self.capacity_bytes, self.protected_target + delta)
        else:
            self.protected_target = max(0, self.protected_target - delta)

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

        from_probation_ghost = key in self.ghost_probation
        from_protected_ghost = key in self.ghost_protected
        if from_probation_ghost:
            self._adapt_target(size, True)
        elif from_protected_ghost:
            self._adapt_target(size, False)
        self._discard_ghost(key)

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            victim = self._replace(from_protected_ghost)
            if victim is None:
                break
            evicted.append(victim)

        if self.used_bytes + size > self.capacity_bytes:
            return evicted

        if from_probation_ghost or from_protected_ghost:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.probation[key] = size
            self.probation_bytes += size
        self.used_bytes += size
        self._rebalance()
        return evicted
