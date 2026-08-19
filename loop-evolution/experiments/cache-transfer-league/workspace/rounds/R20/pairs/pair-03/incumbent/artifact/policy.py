from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0
        self.protected_target = self.capacity_bytes // 2
        self.ghost_limit = max(32, min(4096, self.capacity_bytes // 64 + 32))

    def _remember(self, key, protected):
        first = self.ghost_protected if protected else self.ghost_probation
        second = self.ghost_probation if protected else self.ghost_protected
        second.pop(key, None)
        first.pop(key, None)
        first[key] = None
        while len(first) > self.ghost_limit:
            first.popitem(last=False)

    def _trim_protected(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size

    def _adjust_target(self, increase, size):
        quantum = max(1, self.capacity_bytes // 8)
        step = max(quantum, size)
        if increase:
            self.protected_target = min(self.capacity_bytes, self.protected_target + step)
        else:
            self.protected_target = max(0, self.protected_target - step)

    def _evict_one(self, evicted):
        if self.probation:
            key, size = self.probation.popitem(last=False)
            self._remember(key, False)
        elif self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self._remember(key, True)
        else:
            return False
        self.used_bytes -= size
        evicted.append(key)
        return True

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            self.ghost_probation.pop(key, None)
            self.ghost_protected.pop(key, None)
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            self.ghost_probation.pop(key, None)
            self.ghost_protected.pop(key, None)
            self._trim_protected()
            return []

        if size < 0 or size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        if key in self.ghost_probation:
            self.ghost_probation.pop(key, None)
            self._adjust_target(True, size)
        elif key in self.ghost_protected:
            self.ghost_protected.pop(key, None)
            self._adjust_target(False, size)

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            if not self._evict_one(evicted):
                break

        self.probation[key] = size
        self.used_bytes += size
        self._trim_protected()
        return evicted
