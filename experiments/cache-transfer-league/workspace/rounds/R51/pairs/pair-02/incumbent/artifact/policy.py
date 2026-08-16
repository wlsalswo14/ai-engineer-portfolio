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
        self.protected_bytes = 0
        self.used_bytes = 0

    def _remember(self, ghost, key, size):
        ghost.pop(key, None)
        ghost[key] = size
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

    def _replace(self, from_protected_ghost=False):
        if self.probation and (
            self.protected_bytes >= self.protected_target
            or (from_protected_ghost and self.protected_bytes == self.protected_target)
        ):
            key, size = self.probation.popitem(last=False)
            self._remember(self.ghost_probation, key, size)
        elif self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self._remember(self.ghost_protected, key, size)
        elif self.probation:
            key, size = self.probation.popitem(last=False)
            self._remember(self.ghost_probation, key, size)
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
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            self._rebalance()
            return []

        if size <= 0 or self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        in_probation_ghost = key in self.ghost_probation
        in_protected_ghost = key in self.ghost_protected
        step = max(1, self.capacity_bytes // 16)
        if in_probation_ghost:
            self.protected_target = min(
                self.capacity_bytes,
                self.protected_target + max(step, min(size, self.capacity_bytes)),
            )
        elif in_protected_ghost:
            self.protected_target = max(
                0,
                self.protected_target - max(step, min(size, self.capacity_bytes)),
            )

        self._forget_ghost(key)
        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._replace(in_protected_ghost)
            if old_key is None:
                break
            evicted.append(old_key)

        self.probation[key] = size
        self.used_bytes += size
        self._rebalance()
        return evicted
