from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.used_bytes = 0
        self.probation_target = self.capacity_bytes // 2
        self.ghost_limit = 8192

    def _trim_ghosts(self):
        while len(self.ghost_probation) + len(self.ghost_protected) > self.ghost_limit:
            if len(self.ghost_probation) >= len(self.ghost_protected):
                self.ghost_probation.popitem(last=False)
            else:
                self.ghost_protected.popitem(last=False)

    def _remember_ghost(self, key, size, protected):
        self.ghost_probation.pop(key, None)
        self.ghost_protected.pop(key, None)
        target = self.ghost_protected if protected else self.ghost_probation
        target[key] = size
        self._trim_ghosts()

    def _increase_target(self):
        step = max(1, len(self.ghost_protected) // max(1, len(self.ghost_probation)))
        self.probation_target = min(self.capacity_bytes, self.probation_target + step)

    def _decrease_target(self):
        step = max(1, len(self.ghost_probation) // max(1, len(self.ghost_protected)))
        self.probation_target = max(0, self.probation_target - step)

    def _evict_for(self, incoming_size, prefer_protected):
        evicted = []
        while self.used_bytes + incoming_size > self.capacity_bytes:
            take_probation = bool(self.probation) and (
                self.probation_bytes > self.probation_target
                or (prefer_protected and self.probation_bytes == self.probation_target)
            )
            if take_probation:
                old_key, old_size = self.probation.popitem(last=False)
                self.probation_bytes -= old_size
                self._remember_ghost(old_key, old_size, False)
            elif self.protected:
                old_key, old_size = self.protected.popitem(last=False)
                self.protected_bytes -= old_size
                self._remember_ghost(old_key, old_size, True)
            elif self.probation:
                old_key, old_size = self.probation.popitem(last=False)
                self.probation_bytes -= old_size
                self._remember_ghost(old_key, old_size, False)
            else:
                break
            self.used_bytes -= old_size
            evicted.append(old_key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.probation_bytes -= stored_size
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            return []

        size = max(0, size)
        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        if key in self.ghost_probation:
            self.ghost_probation.pop(key)
            self._increase_target()
            evicted = self._evict_for(size, False)
            self.protected[key] = size
            self.protected_bytes += size
            self.used_bytes += size
            return evicted

        if key in self.ghost_protected:
            self.ghost_protected.pop(key)
            self._decrease_target()
            evicted = self._evict_for(size, True)
            self.protected[key] = size
            self.protected_bytes += size
            self.used_bytes += size
            return evicted

        evicted = self._evict_for(size, False)
        self.probation[key] = size
        self.probation_bytes += size
        self.used_bytes += size
        return evicted
