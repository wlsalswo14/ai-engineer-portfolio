from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.history = OrderedDict()
        self.ghost_limit = 4096
        self.history_limit = 8192
        self.protected_target = self.capacity_bytes // 2
        self.protected_bytes = 0
        self.used_bytes = 0
        self._tick = 0

    def _remember(self, ghost, key):
        ghost.pop(key, None)
        ghost[key] = None
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _remember_history(self, key, frequency):
        previous = self.history.pop(key, 0)
        self.history[key] = min(8, previous + max(1, frequency))
        while len(self.history) > self.history_limit:
            self.history.popitem(last=False)

    def _forget_ghost(self, key):
        self.ghost_probation.pop(key, None)
        self.ghost_protected.pop(key, None)

    def _rebalance(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, entry = self.protected.popitem(last=False)
            self.protected_bytes -= entry[0]
            self.probation[key] = entry

    def _choose_victim(self, table):
        victim_key = None
        victim_entry = None
        for key, entry in table.items():
            if victim_entry is None or (entry[1], entry[2]) < (victim_entry[1], victim_entry[2]):
                victim_key = key
                victim_entry = entry
        return victim_key

    def _evict_one(self):
        if self.probation:
            key = self._choose_victim(self.probation)
            entry = self.probation.pop(key)
            self._remember(self.ghost_probation, key)
        elif self.protected:
            key = self._choose_victim(self.protected)
            entry = self.protected.pop(key)
            self.protected_bytes -= entry[0]
            self._remember(self.ghost_protected, key)
        else:
            return None
        self._remember_history(key, entry[1])
        self.used_bytes -= entry[0]
        return key

    def access(self, key: int, size: int, now: int) -> list[int]:
        self._tick += 1

        if key in self.protected:
            entry = self.protected.pop(key)
            entry[1] = min(255, entry[1] + 1)
            entry[2] = self._tick
            self.protected[key] = entry
            self.history.pop(key, None)
            return []

        if key in self.probation:
            entry = self.probation.pop(key)
            entry[1] = min(255, entry[1] + 1)
            entry[2] = self._tick
            self.protected[key] = entry
            self.protected_bytes += entry[0]
            self.history.pop(key, None)
            self._rebalance()
            return []

        if size <= 0 or self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        step = max(1, self.capacity_bytes // 16)
        in_ghost_probation = key in self.ghost_probation
        in_ghost_protected = key in self.ghost_protected
        if in_ghost_probation:
            self.protected_target = min(
                self.capacity_bytes,
                self.protected_target + max(step, min(size, self.capacity_bytes)),
            )
        elif in_ghost_protected:
            self.protected_target = max(
                0,
                self.protected_target - max(step, min(size, self.capacity_bytes)),
            )

        prior_frequency = self.history.pop(key, 0)
        self._forget_ghost(key)
        initial_frequency = min(
            8,
            max(1, prior_frequency + (1 if in_ghost_probation or in_ghost_protected else 0)),
        )

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._evict_one()
            if old_key is None:
                return []
            evicted.append(old_key)

        self.probation[key] = [size, initial_frequency, self._tick]
        self.used_bytes += size
        self._rebalance()
        return evicted
