from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.items = {}
        self.history = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0
        self.protected_target = self.capacity_bytes // 2
        self.ghost_limit = 4096
        self.history_limit = 8192
        self.clock = 0

    def _remember(self, ghost, key, size, frequency):
        ghost.pop(key, None)
        ghost[key] = (size, frequency)
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)
        self.history.pop(key, None)
        self.history[key] = min(255, frequency)
        while len(self.history) > self.history_limit:
            self.history.popitem(last=False)

    def _forget_ghost(self, key):
        self.ghost_probation.pop(key, None)
        self.ghost_protected.pop(key, None)

    def _adapt(self, key, size):
        delta = max(1, self.capacity_bytes // 16, min(size, self.capacity_bytes))
        if key in self.ghost_probation:
            self.protected_target = min(self.capacity_bytes, self.protected_target + delta)
        elif key in self.ghost_protected:
            self.protected_target = max(0, self.protected_target - delta)
        self._forget_ghost(key)

    def _rebalance(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, _ = self.protected.popitem(last=False)
            entry = self.items.get(key)
            if entry is None:
                continue
            self.protected_bytes -= entry[0]
            entry[1] = 0
            self.probation[key] = None

    def _probation_victim(self):
        victim = None
        best = None
        for index, key in enumerate(self.probation):
            entry = self.items.get(key)
            if entry is not None:
                score = (entry[2], entry[3])
                if best is None or score < best:
                    best = score
                    victim = key
            if index >= 63:
                break
        return victim

    def _evict_one(self):
        if self.probation:
            key = self._probation_victim()
            if key is None:
                return None
            self.probation.pop(key, None)
            entry = self.items.pop(key, None)
            if entry is None:
                return None
            size, _, frequency, _ = entry
            self.used_bytes -= size
            self._remember(self.ghost_probation, key, size, frequency)
            return key
        if self.protected:
            key, _ = self.protected.popitem(last=False)
            entry = self.items.pop(key, None)
            if entry is None:
                return None
            size, _, frequency, _ = entry
            self.protected_bytes -= size
            self.used_bytes -= size
            self._remember(self.ghost_protected, key, size, frequency)
            return key
        return None

    def access(self, key: int, size: int, now: int) -> list[int]:
        self.clock += 1
        entry = self.items.get(key)
        if entry is not None:
            entry[2] = min(255, entry[2] + 1)
            entry[3] = self.clock
            if entry[1] == 0:
                self.probation.pop(key, None)
                entry[1] = 1
                self.protected[key] = None
                self.protected_bytes += entry[0]
                self._rebalance()
            else:
                self.protected.move_to_end(key)
            return []

        if self.capacity_bytes <= 0 or size <= 0 or size > self.capacity_bytes:
            return []

        previous_frequency = self.history.get(key, 0)
        self._adapt(key, size)
        frequency = min(255, previous_frequency + 1)
        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            victim = self._evict_one()
            if victim is None:
                return evicted
            evicted.append(victim)

        self.probation[key] = None
        self.items[key] = [size, 0, frequency, self.clock]
        self.history.pop(key, None)
        self.used_bytes += size
        self._rebalance()
        return evicted
