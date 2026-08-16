from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0
        self.protected_target = self.capacity_bytes // 2

    def _demote_protected(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size

    def _remember(self, key, size, protected):
        self.ghost.pop(key, None)
        self.ghost[key] = (size, protected)
        limit = max(1, 2 * (len(self.probation) + len(self.protected)))
        while len(self.ghost) > limit:
            self.ghost.popitem(last=False)

    def _adjust_target(self, size, was_protected):
        step = max(1, min(size, self.capacity_bytes))
        if was_protected:
            self.protected_target = min(
                self.capacity_bytes, self.protected_target + step
            )
        else:
            self.protected_target = max(0, self.protected_target - step)

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            self._demote_protected()
            return []

        if size < 0 or size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        ghost_entry = self.ghost.pop(key, None)
        if ghost_entry is not None:
            self._adjust_target(size, ghost_entry[1])

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            if self.probation:
                old_key, old_size = self.probation.popitem(last=False)
                self.used_bytes -= old_size
                self._remember(old_key, old_size, False)
            elif self.protected:
                old_key, old_size = self.protected.popitem(last=False)
                self.used_bytes -= old_size
                self.protected_bytes -= old_size
                self._remember(old_key, old_size, True)
            else:
                break
            evicted.append(old_key)

        self.probation[key] = size
        self.used_bytes += size
        return evicted
