from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.recent_ghost = OrderedDict()
        self.frequent_ghost = OrderedDict()
        self.used_bytes = 0
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.recent_ghost_bytes = 0
        self.frequent_ghost_bytes = 0
        self.recent_target = self.capacity_bytes // 2

    def _remove_ghost(self, key):
        if key in self.recent_ghost:
            self.recent_ghost_bytes -= self.recent_ghost.pop(key)
        if key in self.frequent_ghost:
            self.frequent_ghost_bytes -= self.frequent_ghost.pop(key)

    def _add_ghost(self, kind, key, size):
        self._remove_ghost(key)
        if kind == 'recent':
            self.recent_ghost[key] = size
            self.recent_ghost_bytes += size
        else:
            self.frequent_ghost[key] = size
            self.frequent_ghost_bytes += size
        while self.recent_ghost_bytes + self.frequent_ghost_bytes > self.capacity_bytes:
            if self.recent_ghost and (not self.frequent_ghost or self.recent_ghost_bytes >= self.frequent_ghost_bytes):
                _, old_size = self.recent_ghost.popitem(last=False)
                self.recent_ghost_bytes -= old_size
            elif self.frequent_ghost:
                _, old_size = self.frequent_ghost.popitem(last=False)
                self.frequent_ghost_bytes -= old_size
            else:
                break

    def _demote_protected(self):
        target = max(0, self.capacity_bytes - self.recent_target)
        while self.protected and self.protected_bytes > target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size
            self.probation_bytes += size

    def _replace(self, incoming_size, from_frequent_ghost):
        evicted = []
        while self.used_bytes + incoming_size > self.capacity_bytes:
            choose_probation = bool(self.probation) and (
                self.probation_bytes > self.recent_target
                or (from_frequent_ghost and self.probation_bytes == self.recent_target)
            )
            if choose_probation or not self.protected:
                if not self.probation:
                    break
                old_key, old_size = self.probation.popitem(last=False)
                self.probation_bytes -= old_size
                self.used_bytes -= old_size
                self._add_ghost('recent', old_key, old_size)
            else:
                old_key, old_size = self.protected.popitem(last=False)
                self.protected_bytes -= old_size
                self.used_bytes -= old_size
                self._add_ghost('frequent', old_key, old_size)
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
            self._demote_protected()
            return []

        if size > self.capacity_bytes or self.capacity_bytes == 0:
            self._remove_ghost(key)
            return []

        from_frequent_ghost = False
        if key in self.recent_ghost:
            own = max(1, self.recent_ghost_bytes)
            delta = max(1, self.frequent_ghost_bytes // own)
            self.recent_target = min(self.capacity_bytes, self.recent_target + delta)
            self._remove_ghost(key)
            self._demote_protected()
        elif key in self.frequent_ghost:
            own = max(1, self.frequent_ghost_bytes)
            delta = max(1, self.recent_ghost_bytes // own)
            self.recent_target = max(0, self.recent_target - delta)
            self._remove_ghost(key)
            self._demote_protected()
            from_frequent_ghost = True

        evicted = self._replace(size, from_frequent_ghost)
        self.probation[key] = size
        self.probation_bytes += size
        self.used_bytes += size
        return evicted
