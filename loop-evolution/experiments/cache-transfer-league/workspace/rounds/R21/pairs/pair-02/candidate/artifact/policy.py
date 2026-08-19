from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.protected_bytes = 0
        self.used_bytes = 0
        self.frequency = {}
        self.history = OrderedDict()
        self.operations = 0
        self.clock = 0
        self.history_limit = 4096
        self.decay_period = 1024

    def _record(self, key):
        self.operations += 1
        if self.operations % self.decay_period == 0:
            for watched_key in tuple(self.frequency):
                value = self.frequency[watched_key]
                self.frequency[watched_key] = max(1, (value + 1) // 2)
        self.frequency[key] = min(255, self.frequency.get(key, 0) + 1)
        self.history.pop(key, None)
        self.history[key] = None
        while len(self.history) > self.history_limit:
            old_key = next(iter(self.history))
            if old_key in self.probation or old_key in self.protected:
                self.history.move_to_end(old_key)
                break
            self.history.popitem(last=False)
            self.frequency.pop(old_key, None)

    def _rebalance(self):
        target = self.capacity_bytes // 2
        while self.protected and self.protected_bytes > target:
            old_key, entry = self.protected.popitem(last=False)
            self.protected_bytes -= entry[0]
            self.probation[old_key] = entry

    def _select_victim(self):
        segment = self.probation if self.probation else self.protected
        if not segment:
            return None
        victim = None
        victim_rank = None
        for candidate, entry in segment.items():
            size, last = entry
            frequency = self.frequency.get(candidate, 1)
            recurring_bytes = max(0, frequency - 1) * size
            rank = (recurring_bytes, last, -size)
            if victim_rank is None or rank < victim_rank:
                victim = candidate
                victim_rank = rank
        return victim

    def _remove(self, key):
        if key in self.probation:
            entry = self.probation.pop(key)
            self.used_bytes -= entry[0]
            return entry[0]
        if key in self.protected:
            entry = self.protected.pop(key)
            self.protected_bytes -= entry[0]
            self.used_bytes -= entry[0]
            return entry[0]
        return 0

    def access(self, key: int, size: int, now: int) -> list[int]:
        del now
        size = max(0, int(size))
        self.clock += 1
        self._record(key)

        if key in self.protected:
            stored_size, _ = self.protected.pop(key)
            self.protected[key] = (stored_size, self.clock)
            return []

        if key in self.probation:
            stored_size, _ = self.probation.pop(key)
            self.protected[key] = (stored_size, self.clock)
            self.protected_bytes += stored_size
            self._rebalance()
            return []

        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        self._rebalance()
        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            victim = self._select_victim()
            if victim is None:
                return evicted
            self._remove(victim)
            evicted.append(victim)

        self.used_bytes += size
        entry = (size, self.clock)
        if self.frequency.get(key, 1) >= 2:
            self.protected[key] = entry
            self.protected_bytes += size
            self._rebalance()
        else:
            self.probation[key] = entry
        return evicted
