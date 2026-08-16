from collections import OrderedDict


class _InnerPolicy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.ghost_limit = 4096
        self.protected_target = self.capacity_bytes // 2
        self.used_bytes = 0
        self.entries = {}

    def _remember(self, ghost, key):
        ghost.pop(key, None)
        ghost[key] = None
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _forget_ghost(self, key):
        self.ghost_probation.pop(key, None)
        self.ghost_protected.pop(key, None)

    def _rebalance(self):
        protected_bytes = sum(self.protected.values())
        while self.protected and protected_bytes > self.protected_target:
            old_key, old_size = self.protected.popitem(last=False)
            self.probation[old_key] = old_size
            self.entries[old_key] = (old_size, 0)
            protected_bytes -= old_size

    def _evict_one(self):
        if self.probation:
            old_key, old_size = self.probation.popitem(last=False)
            self._remember(self.ghost_probation, old_key)
        elif self.protected:
            old_key, old_size = self.protected.popitem(last=False)
            self._remember(self.ghost_protected, old_key)
        else:
            return None
        self.entries.pop(old_key, None)
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
            self.entries[key] = (stored_size, 1)
            self._rebalance()
            return []

        if size <= 0 or size > self.capacity_bytes or self.capacity_bytes == 0:
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

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._evict_one()
            if old_key is None:
                break
            evicted.append(old_key)

        self.probation[key] = size
        self.entries[key] = (size, 0)
        self.used_bytes += size
        self._rebalance()
        return evicted


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self._inner = _InnerPolicy(capacity_bytes)
        self._cached = OrderedDict()

    def access(self, key: int, size: int, now: int) -> list[int]:
        inner_evicted = self._inner.access(key, size, now)
        evicted = []
        seen = set()
        for old_key in inner_evicted:
            if not isinstance(old_key, int) or old_key in seen:
                continue
            if old_key in self._cached:
                seen.add(old_key)
                self._cached.pop(old_key, None)
                evicted.append(old_key)

        if key not in self._cached and 0 < size <= self.capacity_bytes:
            self._cached[key] = size

        return evicted
