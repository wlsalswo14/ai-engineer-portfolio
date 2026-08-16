from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.ghost_limit = 4096
        self.protected_target = self.capacity_bytes // 2
        self.protected_bytes = 0
        self.used_bytes = 0
        self._frequency = {}
        self._operations = 0

    def _tick(self):
        self._operations += 1
        if self._operations % 4096 == 0:
            for key in list(self._frequency):
                self._frequency[key] = max(1, self._frequency[key] // 2)

    def _touch(self, key):
        self._frequency[key] = self._frequency.get(key, 0) + 1

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

    def _victim(self):
        if self.probation:
            key, size = next(iter(self.probation.items()))
            best_frequency = self._frequency.get(key, 1)
            inspected = 0
            for candidate, candidate_size in self.probation.items():
                if inspected >= 8:
                    break
                candidate_frequency = self._frequency.get(candidate, 1)
                if candidate_frequency < best_frequency:
                    key = candidate
                    size = candidate_size
                    best_frequency = candidate_frequency
                inspected += 1
            return key, size, False
        if self.protected:
            key, size = next(iter(self.protected.items()))
            return key, size, True
        return None

    def _evict_one(self):
        victim = self._victim()
        if victim is None:
            return None
        key, size, from_protected = victim
        if from_protected:
            self.protected.pop(key)
            self.protected_bytes -= size
            self._remember(self.ghost_protected, key)
        else:
            self.probation.pop(key)
            self._remember(self.ghost_probation, key)
        self._frequency.pop(key, None)
        self.used_bytes -= size
        return key

    def access(self, key: int, size: int, now: int) -> list[int]:
        self._tick()

        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            self._touch(key)
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            self._touch(key)
            self._rebalance()
            return []

        if size <= 0 or self.capacity_bytes == 0 or size > self.capacity_bytes:
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
                return evicted
            evicted.append(old_key)

        self.probation[key] = size
        self.used_bytes += size
        self._frequency[key] = 1
        self._rebalance()
        return evicted
