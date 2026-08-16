from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0
        self.ghost_limit = 4096

    def _record_eviction(self, key):
        self.ghost.pop(key, None)
        self.ghost[key] = None
        while len(self.ghost) > self.ghost_limit:
            self.ghost.popitem(last=False)

    def _demote_protected(self):
        target = self.capacity_bytes // 2
        while self.protected and self.protected_bytes > target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size

    def _make_room(self, size, evicted):
        while self.used_bytes + size > self.capacity_bytes:
            if self.probation:
                old_key, old_size = self.probation.popitem(last=False)
            elif self.protected:
                old_key, old_size = self.protected.popitem(last=False)
                self.protected_bytes -= old_size
            else:
                break
            self.used_bytes -= old_size
            self._record_eviction(old_key)
            evicted.append(old_key)

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

        if size < 0:
            size = 0
        if size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        was_ghost = key in self.ghost
        self.ghost.pop(key, None)
        evicted = []
        self._make_room(size, evicted)

        if was_ghost:
            self.protected[key] = size
            self.protected_bytes += size
            self._demote_protected()
        else:
            self.probation[key] = size

        self.used_bytes += size
        return evicted
