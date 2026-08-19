from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.recent_ghost = OrderedDict()
        self.protected_ghost = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0
        self.protected_target = self.capacity_bytes // 2
        self.ghost_limit = 2048

    def _remember(self, ghost, key):
        ghost.pop(key, None)
        ghost[key] = None
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _adjust_target(self, increase):
        step = max(1, self.capacity_bytes // 16)
        if increase:
            self.protected_target = min(
                self.capacity_bytes, self.protected_target + step
            )
        else:
            self.protected_target = max(0, self.protected_target - step)

    def _trim_protected(self):
        while self.protected and self.protected_bytes > self.protected_target:
            old_key, old_size = self.protected.popitem(last=False)
            self.protected_bytes -= old_size
            self.probation[old_key] = old_size

    def _evict_one(self):
        if self.probation:
            old_key, old_size = self.probation.popitem(last=False)
            self._remember(self.recent_ghost, old_key)
        elif self.protected:
            old_key, old_size = self.protected.popitem(last=False)
            self.protected_bytes -= old_size
            self._remember(self.protected_ghost, old_key)
        else:
            return None
        self.used_bytes -= old_size
        return old_key

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            self._trim_protected()
            return []

        if self.capacity_bytes == 0 or size <= 0 or size > self.capacity_bytes:
            return []

        in_recent_ghost = key in self.recent_ghost
        in_protected_ghost = key in self.protected_ghost
        if in_recent_ghost:
            self._adjust_target(True)
        elif in_protected_ghost:
            self._adjust_target(False)

        self.recent_ghost.pop(key, None)
        self.protected_ghost.pop(key, None)

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._evict_one()
            if old_key is None:
                break
            evicted.append(old_key)

        if in_recent_ghost or in_protected_ghost:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.probation[key] = size
        self.used_bytes += size
        self._trim_protected()
        return evicted
