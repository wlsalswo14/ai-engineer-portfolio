from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost = OrderedDict()
        self.ghost_limit = 4096
        self.protected_target = self.capacity_bytes // 2
        self.used_bytes = 0
        self.frequency = OrderedDict()

    def _touch_frequency(self, key):
        count = self.frequency.pop(key, 0)
        self.frequency[key] = min((1 << 20), count + 1)
        while len(self.frequency) > 8192:
            self.frequency.popitem(last=False)

    def _remember(self, key, segment):
        self.ghost.pop(key, None)
        self.ghost[key] = segment
        while len(self.ghost) > self.ghost_limit:
            self.ghost.popitem(last=False)

    def _rebalance(self):
        protected_bytes = sum(self.protected.values())
        while self.protected and protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.probation[key] = size
            protected_bytes -= size

    def _peek_victim(self):
        if self.probation:
            return next(iter(self.probation.items()))
        if self.protected:
            return next(iter(self.protected.items()))
        return None

    def _evict_one(self):
        if self.probation:
            key, size = self.probation.popitem(last=False)
            segment = 0
        elif self.protected:
            key, size = self.protected.popitem(last=False)
            segment = 1
        else:
            return None
        self.used_bytes -= size
        self._remember(key, segment)
        return key

    def _admit(self, key, size, ghost_hit):
        if ghost_hit or self.used_bytes + size <= self.capacity_bytes:
            return True
        victim = self._peek_victim()
        if victim is None:
            return True
        victim_key, victim_size = victim
        candidate_frequency = self.frequency.get(key, 1)
        victim_frequency = self.frequency.get(victim_key, 1)
        return candidate_frequency * victim_size >= victim_frequency * size

    def access(self, key: int, size: int, now: int) -> list[int]:
        self._touch_frequency(key)

        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.protected[key] = stored_size
            self._rebalance()
            return []

        if self.capacity_bytes == 0 or size <= 0 or size > self.capacity_bytes:
            return []

        ghost_hit = key in self.ghost
        if ghost_hit:
            segment = self.ghost.pop(key)
            step = max(1, self.capacity_bytes // 16)
            adjustment = max(step, min(size, self.capacity_bytes))
            if segment == 0:
                self.protected_target = min(
                    self.capacity_bytes, self.protected_target + adjustment
                )
            else:
                self.protected_target = max(0, self.protected_target - adjustment)

        self._rebalance()
        if not self._admit(key, size, ghost_hit):
            return []

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
