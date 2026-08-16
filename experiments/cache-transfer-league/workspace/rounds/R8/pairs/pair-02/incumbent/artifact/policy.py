from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.protected_bytes = 0
        self.used_bytes = 0
        self.ghost = OrderedDict()
        self.ghost_limit = 256

    def _remember(self, key, segment):
        self.ghost.pop(key, None)
        self.ghost[key] = segment
        while len(self.ghost) > self.ghost_limit:
            self.ghost.popitem(last=False)

    def _demote_protected(self):
        target = self.capacity_bytes // 2
        while self.protected and self.protected_bytes > target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size

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

        size = max(0, int(size))
        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        ghost_segment = self.ghost.pop(key, None)
        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            if self.probation:
                old_key, old_size = self.probation.popitem(last=False)
                self._remember(old_key, 0)
            elif self.protected:
                old_key, old_size = self.protected.popitem(last=False)
                self.protected_bytes -= old_size
                self._remember(old_key, 1)
            else:
                break
            self.used_bytes -= old_size
            evicted.append(old_key)

        if ghost_segment == 1:
            self.protected[key] = size
            self.protected_bytes += size
            self._demote_protected()
        else:
            self.probation[key] = size

        self.used_bytes += size
        return evicted
