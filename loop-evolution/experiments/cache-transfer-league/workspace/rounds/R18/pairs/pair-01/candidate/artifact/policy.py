from collections import OrderedDict, deque


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.entries = {}
        self.frequency = {}
        self.used_bytes = 0
        self.protected_bytes = 0
        self.protected_ratio = 0.60
        self.access_count = 0
        self.last_now = None
        self.recent = deque()
        self.recent_counts = {}
        self.recent_limit = 512
        self.window_protected_hits = 0
        self.window_probation_hits = 0

    def _remember(self, key):
        if len(self.recent) >= self.recent_limit:
            old = self.recent.popleft()
            count = self.recent_counts.get(old, 0)
            if count <= 1:
                self.recent_counts.pop(old, None)
            else:
                self.recent_counts[old] = count - 1
        self.recent.append(key)
        self.recent_counts[key] = self.recent_counts.get(key, 0) + 1

    def _decay_frequencies(self):
        for key, value in list(self.frequency.items()):
            value = (value + 1) // 2
            if value <= 0:
                self.frequency.pop(key, None)
            else:
                self.frequency[key] = value

    def _observe_time(self, now):
        if self.last_now is not None:
            try:
                gap = now - self.last_now
            except Exception:
                gap = 0
            if gap > 1024:
                self._decay_frequencies()
                self.recent.clear()
                self.recent_counts.clear()
                self.protected_ratio = max(0.45, self.protected_ratio - 0.10)
        self.last_now = now

    def _demote_one(self):
        if not self.protected:
            return False
        key, _ = self.protected.popitem(last=False)
        entry = self.entries[key]
        self.protected_bytes -= entry[0]
        entry[1] = 'probation'
        self.probation[key] = None
        return True

    def _rebalance(self):
        target = int(self.capacity_bytes * self.protected_ratio)
        while self.protected and self.protected_bytes > target:
            self._demote_one()

    def _utility(self, key):
        entry = self.entries[key]
        age = self.access_count - entry[2]
        recency = max(1, 64 - min(63, age))
        recent = min(8, self.recent_counts.get(key, 0))
        value = self.frequency.get(key, 1) * 16 + recency + recent * 8
        return (value * 1024) // max(1, entry[0])

    def _pick_victim(self):
        if not self.probation and not self._demote_one():
            return None
        best_key = None
        best_score = None
        for key in self.probation:
            score = self._utility(key)
            if best_score is None or score < best_score:
                best_key = key
                best_score = score
        return best_key

    def _remove(self, key):
        entry = self.entries.pop(key)
        if entry[1] == 'protected':
            self.protected.pop(key, None)
            self.protected_bytes -= entry[0]
        else:
            self.probation.pop(key, None)
        self.used_bytes -= entry[0]
        return entry[0]

    def _maintenance(self):
        if self.access_count % 128 != 0:
            return
        if self.window_protected_hits > self.window_probation_hits + 3:
            self.protected_ratio = min(0.75, self.protected_ratio + 0.05)
        elif self.window_probation_hits > self.window_protected_hits + 3:
            self.protected_ratio = max(0.45, self.protected_ratio - 0.05)
        self.window_protected_hits = 0
        self.window_probation_hits = 0
        self._decay_frequencies()
        self._rebalance()

    def access(self, key: int, size: int, now: int) -> list[int]:
        self.access_count += 1
        self._observe_time(now)
        self._remember(key)

        entry = self.entries.get(key)
        if entry is not None:
            if entry[1] == 'protected':
                self.protected.pop(key, None)
                self.protected[key] = None
                self.window_protected_hits += 1
            else:
                self.probation.pop(key, None)
                self.probation[key] = None
                entry[1] = 'protected'
                self.protected_bytes += entry[0]
                self.window_probation_hits += 1
            entry[2] = self.access_count
            self.frequency[key] = min(255, self.frequency.get(key, 0) + 1)
            self._rebalance()
            self._maintenance()
            return []

        if self.capacity_bytes == 0 or size <= 0 or size > self.capacity_bytes:
            self._maintenance()
            return []

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            victim = self._pick_victim()
            if victim is None:
                break
            self._remove(victim)
            evicted.append(victim)

        if self.used_bytes + size <= self.capacity_bytes:
            self.entries[key] = [size, 'probation', self.access_count]
            self.probation[key] = None
            self.frequency[key] = max(1, self.frequency.get(key, 0))
            self.used_bytes += size
            self._rebalance()

        self._maintenance()
        return evicted
