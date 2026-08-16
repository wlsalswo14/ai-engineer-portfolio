from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.history = OrderedDict()
        self.history_limit = 8192
        self.ghost_limit = 4096
        self.protected_target = self.capacity_bytes // 2
        self.used_bytes = 0
        self.access_count = 0

    def _record(self, key):
        value = self.history.pop(key, 0) + 1
        self.history[key] = value
        while len(self.history) > self.history_limit:
            old_key, _ = self.history.popitem(last=False)
            if old_key in self.probation or old_key in self.protected:
                self.history[old_key] = value
                break
        self.access_count += 1
        if self.access_count % 2048 == 0:
            for item_key in list(self.history):
                self.history[item_key] = max(1, (self.history[item_key] + 1) // 2)

    def _remember(self, ghost, key):
        ghost.pop(key, None)
        ghost[key] = None
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _forget_ghost(self, key):
        self.ghost_probation.pop(key, None)
        self.ghost_protected.pop(key, None)

    def _frequency(self, key):
        return self.history.get(key, 1)

    def _rebalance(self):
        protected_bytes = sum(self.protected.values())
        while self.protected and protected_bytes > self.protected_target:
            old_key, old_size = self.protected.popitem(last=False)
            self.probation[old_key] = old_size
            protected_bytes -= old_size

    def _victim(self):
        if self.probation:
            return next(iter(self.probation))
        if self.protected:
            return next(iter(self.protected))
        return None

    def _evict_one(self):
        if self.probation:
            old_key, old_size = self.probation.popitem(last=False)
            self._remember(self.ghost_probation, old_key)
        elif self.protected:
            old_key, old_size = self.protected.popitem(last=False)
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

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.protected[key] = stored_size
            self._rebalance()
            return []

        if size <= 0 or size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        if key in self.ghost_probation:
            step = max(1, self.capacity_bytes // 16)
            self.protected_target = max(0, self.protected_target - max(step, min(size, self.capacity_bytes)))
        elif key in self.ghost_protected:
            step = max(1, self.capacity_bytes // 16)
            self.protected_target = min(self.capacity_bytes, self.protected_target + max(step, min(size, self.capacity_bytes)))

        victim = self._victim()
        if victim is not None:
            new_score = self._frequency(key) / max(1, size)
            old_size = self.probation.get(victim, self.protected.get(victim, 1))
            old_score = self._frequency(victim) / max(1, old_size)
            if key not in self.ghost_probation and key not in self.ghost_protected and new_score < old_score:
                self._forget_ghost(key)
                return []

        self._forget_ghost(key)
        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._evict_one()
            if old_key is None:
                return evicted
            evicted.append(old_key)

        self.probation[key] = size
        self.used_bytes += size
        self._rebalance()
        return evicted
