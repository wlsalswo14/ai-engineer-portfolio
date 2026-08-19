from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.protected = OrderedDict()
        self.ghost = OrderedDict()
        self.frequency = {}
        self.used_bytes = 0
        self.requests = 0
        self.protected_ratio = 0.70
        self.recent_hits = 0
        self.protected_hits = 0
        self.ghost_hits = 0
        self.misses = 0
        self.miss_streak = 0
        self.ghost_limit = 4096

    def _protected_target(self):
        return int(self.capacity_bytes * self.protected_ratio)

    def _rebalance(self):
        target = self._protected_target()
        protected_bytes = sum(self.protected.values())
        while self.protected and protected_bytes > target:
            key, size = self.protected.popitem(last=False)
            self.recent[key] = size
            protected_bytes -= size

    def _age(self):
        for key in list(self.frequency):
            value = self.frequency[key] >> 1
            if value:
                self.frequency[key] = value
            else:
                del self.frequency[key]

    def _finish_request(self):
        if self.requests % 64 == 0:
            recent_signal = self.recent_hits + 2 * self.ghost_hits
            protected_signal = self.protected_hits
            if recent_signal > protected_signal + 2:
                self.protected_ratio = max(0.35, self.protected_ratio - 0.08)
            elif protected_signal > recent_signal + 2:
                self.protected_ratio = min(0.85, self.protected_ratio + 0.08)
            if self.misses > recent_signal + protected_signal + 8:
                self.protected_ratio = max(0.35, self.protected_ratio - 0.04)
            self.recent_hits = 0
            self.protected_hits = 0
            self.ghost_hits = 0
            self.misses = 0
        if self.requests % 256 == 0:
            self._age()
        self._rebalance()

    def _utility(self, key, size, protected):
        frequency = min(32, self.frequency.get(key, 0))
        byte_term = (frequency * min(size, self.capacity_bytes) * 8) // max(1, self.capacity_bytes)
        return frequency * 16 + byte_term + (8 if protected else 0)

    def _victim(self):
        candidates = []
        for rank, (key, size) in enumerate(list(self.recent.items())[:16]):
            candidates.append((self._utility(key, size, False), 0, rank, key))
        for rank, (key, size) in enumerate(list(self.protected.items())[:16]):
            candidates.append((self._utility(key, size, True), 1, rank, key))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        return candidates[0][3]

    def _remove(self, key):
        if key in self.recent:
            size = self.recent.pop(key)
        else:
            size = self.protected.pop(key)
        self.used_bytes -= size
        if self.used_bytes < 0:
            self.used_bytes = 0
        self.ghost[key] = size
        self.ghost.move_to_end(key)
        while len(self.ghost) > self.ghost_limit:
            self.ghost.popitem(last=False)
        return size

    def access(self, key: int, size: int, now: int) -> list[int]:
        self.requests += 1
        self.frequency[key] = self.frequency.get(key, 0) + 1

        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            self.protected_hits += 1
            self.miss_streak = 0
            self._finish_request()
            return []

        if key in self.recent:
            stored_size = self.recent.pop(key)
            self.protected[key] = stored_size
            self.recent_hits += 1
            self.miss_streak = 0
            self._finish_request()
            return []

        self.misses += 1
        self.miss_streak += 1
        ghost_hit = key in self.ghost
        if ghost_hit:
            self.ghost_hits += 1

        if self.capacity_bytes == 0 or size <= 0 or size > self.capacity_bytes:
            self._finish_request()
            return []

        if (self.used_bytes + size > self.capacity_bytes and
                not ghost_hit and
                self.frequency.get(key, 0) <= 1 and
                self.miss_streak >= 4 and
                size * 2 > self.capacity_bytes and
                self.protected):
            self._finish_request()
            return []

        self._rebalance()
        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            victim = self._victim()
            if victim is None:
                break
            self._remove(victim)
            evicted.append(victim)

        if self.used_bytes + size <= self.capacity_bytes:
            self.ghost.pop(key, None)
            self.recent[key] = size
            self.used_bytes += size

        self._finish_request()
        return evicted
