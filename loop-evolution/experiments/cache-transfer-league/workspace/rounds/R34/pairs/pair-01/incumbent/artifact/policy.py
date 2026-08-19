from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.ghost_limit = 4096
        self.protected_target = self.capacity_bytes // 2
        self.protected_bytes = 0
        self.used_bytes = 0
        self.frequency = {}
        self.request_count = 0

    def _age_frequency(self):
        for key, value in list(self.frequency.items()):
            value //= 2
            if value:
                self.frequency[key] = value
            else:
                del self.frequency[key]

    def _record(self, key):
        self.request_count += 1
        if self.request_count % 512 == 0:
            self._age_frequency()
        self.frequency[key] = min(255, self.frequency.get(key, 0) + 1)

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
            key, stored_size = self.protected.popitem(last=False)
            self.protected_bytes -= stored_size
            self.probation[key] = stored_size

    def _evict_one(self):
        if self.probation:
            key, stored_size = self.probation.popitem(last=False)
            self._remember(self.ghost_probation, key)
        elif self.protected:
            key, stored_size = self.protected.popitem(last=False)
            self.protected_bytes -= stored_size
            self._remember(self.ghost_protected, key)
        else:
            return None
        self.used_bytes -= stored_size
        return key

    def _should_admit(self, key):
        if self.used_bytes < self.capacity_bytes:
            return True
        if self.probation:
            victim = next(iter(self.probation))
        elif self.protected:
            victim = next(iter(self.protected))
        else:
            return True
        return self.frequency.get(key, 0) >= self.frequency.get(victim, 0)

    def access(self, key: int, size: int, now: int) -> list[int]:
        self._record(key)

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

        if not self._should_admit(key):
            return []

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._evict_one()
            if old_key is None:
                return evicted
            evicted.append(old_key)

        self.probation[key] = size
        self.used_bytes += size
        return evicted
