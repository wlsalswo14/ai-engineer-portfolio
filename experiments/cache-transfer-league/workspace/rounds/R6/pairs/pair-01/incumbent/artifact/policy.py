from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.used_bytes = 0
        self.protected_target = self.capacity_bytes // 2
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.ghost_limit = 512

    def _remember_ghost(self, key, protected):
        self.ghost_probation.pop(key, None)
        self.ghost_protected.pop(key, None)
        target = self.ghost_protected if protected else self.ghost_probation
        target[key] = None
        while len(self.ghost_probation) + len(self.ghost_protected) > self.ghost_limit:
            if self.ghost_probation:
                self.ghost_probation.popitem(last=False)
            elif self.ghost_protected:
                self.ghost_protected.popitem(last=False)
            else:
                break

    def _adjust_from_ghost(self, key):
        step = max(1, self.capacity_bytes // 8)
        if key in self.ghost_protected:
            self.protected_target = min(self.capacity_bytes, self.protected_target + step)
        elif key in self.ghost_probation:
            self.protected_target = max(0, self.protected_target - step)
        self.ghost_probation.pop(key, None)
        self.ghost_protected.pop(key, None)

    def _demote_protected(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size
            self.probation_bytes += size

    def _evict_one(self):
        if self.probation:
            key, size = self.probation.popitem(last=False)
            self.probation_bytes -= size
            self.used_bytes -= size
            self._remember_ghost(key, False)
            return key
        if self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.used_bytes -= size
            self._remember_ghost(key, True)
            return key
        return None

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

        if self.capacity_bytes == 0 or size < 0 or size > self.capacity_bytes:
            return []

        self._adjust_from_ghost(key)
        if size > self.protected_target:
            self.protected_target = min(self.capacity_bytes, size)

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._evict_one()
            if old_key is None:
                break
            evicted.append(old_key)

        if self.used_bytes + size > self.capacity_bytes:
            return evicted

        self.probation[key] = size
        self.probation_bytes += size
        self.used_bytes += size
        return evicted
