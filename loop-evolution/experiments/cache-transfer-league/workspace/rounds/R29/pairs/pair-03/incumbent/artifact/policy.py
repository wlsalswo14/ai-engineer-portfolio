from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.ghost_limit = 4096
        self.protected_target = (self.capacity_bytes * 2) // 3
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

    def _evict_one(self, excluded=None):
        for segment, ghost, is_protected in (
            (self.probation, self.ghost_probation, False),
            (self.protected, self.ghost_protected, True),
        ):
            victim = None
            for candidate in segment:
                if candidate != excluded:
                    victim = candidate
                    break
            if victim is None:
                continue
            size = segment.pop(victim)
            self._remember(ghost, victim)
            if is_protected:
                self.protected_bytes -= size
            self.used_bytes -= size
            return victim
        return None

    def _trim(self, excluded=None):
        evicted = []
        while self.used_bytes > self.capacity_bytes:
            victim = self._evict_one(excluded)
            if victim is None:
                break
            evicted.append(victim)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            old_size = self.protected.pop(key)
            new_size = size if size > 0 else old_size
            if new_size > self.capacity_bytes:
                self.protected_bytes -= old_size
                self.used_bytes -= old_size
                self._remember(self.ghost_protected, key)
                return [key]
            self.protected[key] = new_size
            self.protected_bytes += new_size - old_size
            self.used_bytes += new_size - old_size
            return self._trim()

        if key in self.probation:
            old_size = self.probation.pop(key)
            new_size = size if size > 0 else old_size
            if new_size > self.capacity_bytes:
                self.used_bytes -= old_size
                self._remember(self.ghost_probation, key)
                return [key]
            self.protected[key] = new_size
            self.protected_bytes += new_size
            self.used_bytes += new_size - old_size
            self._rebalance()
            return self._trim()

        if self.capacity_bytes == 0 or size <= 0 or size > self.capacity_bytes:
            return []

        step = max(1, self.capacity_bytes // 16)
        if key in self.ghost_probation:
            self.protected_target = min(
                self.capacity_bytes,
                self.protected_target + max(step, min(size, self.capacity_bytes)),
            )
        elif key in self.ghost_protected:
            self.protected_target = max(
                0,
                self.protected_target - max(step, min(size, self.capacity_bytes)),
            )
        self._forget_ghost(key)
        self._rebalance()

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            victim = self._evict_one()
            if victim is None:
                return evicted
            evicted.append(victim)

        self.probation[key] = size
        self.used_bytes += size
        self._rebalance()
        return evicted
