from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost = OrderedDict()
        self.used_bytes = 0
        self.ghost_bytes = 0

    def _remember(self, key, size):
        if size <= 0 or size > self.capacity_bytes:
            return
        old = self.ghost.pop(key, None)
        if old is not None:
            self.ghost_bytes -= old
        self.ghost[key] = size
        self.ghost_bytes += size
        while self.ghost and self.ghost_bytes > self.capacity_bytes:
            _, old_size = self.ghost.popitem(last=False)
            self.ghost_bytes -= old_size

    def _demote_protected(self):
        target = self.capacity_bytes // 2
        protected_bytes = sum(self.protected.values())
        while self.protected and protected_bytes > target:
            key, size = self.protected.popitem(last=False)
            protected_bytes -= size
            self.probation[key] = size

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.protected[key] = stored_size
            self._demote_protected()
            return []

        if size <= 0 or size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        was_recently_evicted = key in self.ghost
        old_ghost_size = self.ghost.pop(key, None)
        if old_ghost_size is not None:
            self.ghost_bytes -= old_ghost_size

        evicted = []
        self._demote_protected()
        while self.used_bytes + size > self.capacity_bytes:
            if self.probation:
                old_key, old_size = self.probation.popitem(last=False)
            elif self.protected:
                old_key, old_size = self.protected.popitem(last=False)
            else:
                break
            self.used_bytes -= old_size
            self._remember(old_key, old_size)
            evicted.append(old_key)

        if was_recently_evicted:
            self.protected[key] = size
        else:
            self.probation[key] = size
        self.used_bytes += size
        self._demote_protected()
        return evicted
