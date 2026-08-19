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

    def _remember(self, ghost, key):
        ghost.pop(key, None)
        ghost[key] = None
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _remember_history(self, key, frequency):
        self.history.pop(key, None)
        self.history[key] = frequency
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

    def _probation_victim(self):
        best_key = None
        best_entry = None
        examined = 0
        for key, entry in self.probation.items():
            if examined >= 16:
                break
            examined += 1
            if best_entry is None:
                best_key = key
                best_entry = entry
                continue
            if entry[1] < best_entry[1]:
                best_key = key
                best_entry = entry
            elif entry[1] == best_entry[1] and entry[0] > best_entry[0]:
                best_key = key
                best_entry = entry
        return best_key

    def _evict_one(self):
        if self.probation:
            key = self._probation_victim()
            entry = self.probation.pop(key)
            self._remember(self.ghost_probation, key)
        elif self.protected:
            key, entry = self.protected.popitem(last=False)
            self.protected_bytes -= entry[0]
            self._remember(self.ghost_protected, key)
        else:
            return None
        self._remember_history(key, entry[1])
        self.used_bytes -= entry[0]
        return key

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            entry = self.protected.pop(key)
            entry[1] += 1
            self.protected[key] = entry
            return []

        if key in self.probation:
            entry = self.probation.pop(key)
            entry[1] += 1
            self.protected[key] = entry
            self.protected_bytes += entry[0]
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

        prior_frequency = self.history.pop(key, 0)
        frequency = prior_frequency + 1
        self._forget_ghost(key)

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._evict_one()
            if old_key is None:
                break
            evicted.append(old_key)

        self.probation[key] = [size, frequency]
        self.used_bytes += size
        self._rebalance()
        return evicted
