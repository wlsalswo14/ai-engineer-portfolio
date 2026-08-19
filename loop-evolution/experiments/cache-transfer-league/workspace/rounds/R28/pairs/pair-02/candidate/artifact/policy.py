from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.window = OrderedDict()
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.window_bytes = 0
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.used_bytes = 0
        self.window_target = min(self.capacity_bytes, max(1, self.capacity_bytes // 8)) if self.capacity_bytes else 0
        self.protected_target = max(1, self.capacity_bytes // 2) if self.capacity_bytes else 0
        self.ghost_window = OrderedDict()
        self.ghost_main = OrderedDict()
        self.ghost_limit = 4096
        self.frequency = {}
        self.tick = 0
        self.observational = True
        self.intervention_grounded = False

    def _remember(self, ghost, key, size):
        self.ghost_window.pop(key, None)
        self.ghost_main.pop(key, None)
        ghost[key] = size
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _forget_ghost(self, key):
        self.ghost_window.pop(key, None)
        self.ghost_main.pop(key, None)

    def _observe(self, key):
        self.tick += 1
        previous = self.frequency.get(key, 0)
        self.frequency[key] = min(255, previous + 1)
        if previous > 0 or key in self.ghost_window or key in self.ghost_main:
            self.observational = False
            self.intervention_grounded = True
        if self.tick % 2048 == 0:
            for observed_key in tuple(self.frequency):
                reduced = self.frequency[observed_key] // 2
                if reduced:
                    self.frequency[observed_key] = reduced
                else:
                    del self.frequency[observed_key]

    def _adapt(self, key, size):
        if key in self.ghost_window:
            delta = max(1, self.capacity_bytes // 16, min(size, self.capacity_bytes))
            self.window_target = min(self.capacity_bytes, self.window_target + delta)
            self.observational = False
            self.intervention_grounded = True
        elif key in self.ghost_main:
            delta = max(1, self.capacity_bytes // 16, min(size, self.capacity_bytes))
            self.window_target = max(1, self.window_target - delta)
            self.observational = False
            self.intervention_grounded = True
        self._forget_ghost(key)

    def _rebalance_protected(self):
        while self.protected and self.protected_bytes > self.protected_target:
            old_key, old_size = self.protected.popitem(last=False)
            self.protected_bytes -= old_size
            self.probation[old_key] = old_size
            self.probation_bytes += old_size

    def _probation_victim(self):
        if not self.probation:
            return None
        if self.observational:
            return next(iter(self.probation))
        best_key = None
        best_value = None
        for position, candidate in enumerate(self.probation):
            value = (self.frequency.get(candidate, 0), position)
            if best_value is None or value < best_value:
                best_key = candidate
                best_value = value
            if position >= 63:
                break
        return best_key

    def _evict_one(self):
        if self.probation:
            old_key = self._probation_victim()
            old_size = self.probation.pop(old_key)
            self.probation_bytes -= old_size
            self._remember(self.ghost_main, old_key, old_size)
        elif self.protected:
            old_key, old_size = self.protected.popitem(last=False)
            self.protected_bytes -= old_size
            self._remember(self.ghost_main, old_key, old_size)
        elif self.window:
            old_key, old_size = self.window.popitem(last=False)
            self.window_bytes -= old_size
            self._remember(self.ghost_window, old_key, old_size)
        else:
            return None
        self.used_bytes -= old_size
        return old_key

    def access(self, key: int, size: int, now: int) -> list[int]:
        self._observe(key)
        _ = now

        if key in self.window:
            stored_size = self.window.pop(key)
            self.window[key] = stored_size
            return []

        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.probation_bytes -= stored_size
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            self._rebalance_protected()
            return []

        if self.capacity_bytes == 0 or size <= 0 or size > self.capacity_bytes:
            return []

        self._adapt(key, size)
        self.window[key] = size
        self.window_bytes += size
        self.used_bytes += size

        while self.window and self.window_bytes > self.window_target:
            old_key, old_size = self.window.popitem(last=False)
            self.window_bytes -= old_size
            self.probation[old_key] = old_size
            self.probation_bytes += old_size

        self._rebalance_protected()
        evicted = []
        while self.used_bytes > self.capacity_bytes:
            old_key = self._evict_one()
            if old_key is None:
                break
            evicted.append(old_key)
        return evicted
