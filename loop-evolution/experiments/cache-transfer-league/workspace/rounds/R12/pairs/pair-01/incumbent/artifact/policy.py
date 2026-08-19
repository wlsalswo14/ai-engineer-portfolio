from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0
        self.protected_target_bytes = self.capacity_bytes // 2

    def _trim_ghosts(self):
        limit = max(1, 2 * (len(self.probation) + len(self.protected)))
        while len(self.ghost_recent) + len(self.ghost_protected) > limit:
            if self.ghost_recent:
                self.ghost_recent.popitem(last=False)
            elif self.ghost_protected:
                self.ghost_protected.popitem(last=False)

    def _record_recent_ghost(self, key):
        self.ghost_protected.pop(key, None)
        self.ghost_recent.pop(key, None)
        self.ghost_recent[key] = None
        self._trim_ghosts()

    def _record_protected_ghost(self, key):
        self.ghost_recent.pop(key, None)
        self.ghost_protected.pop(key, None)
        self.ghost_protected[key] = None
        self._trim_ghosts()

    def _demote_protected(self):
        while self.protected and self.protected_bytes > self.protected_target_bytes:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size

    def _evict_one(self, evicted):
        if self.probation:
            key, size = self.probation.popitem(last=False)
            self.used_bytes -= size
            self._record_recent_ghost(key)
        elif self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.used_bytes -= size
            self._record_protected_ghost(key)
        else:
            return False
        evicted.append(key)
        return True

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

        if size < 0 or self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        if key in self.ghost_recent:
            self.ghost_recent.pop(key, None)
            step = max(1, size, self.capacity_bytes // 16)
            self.protected_target_bytes = max(0, self.protected_target_bytes - step)
        elif key in self.ghost_protected:
            self.ghost_protected.pop(key, None)
            step = max(1, size, self.capacity_bytes // 16)
            self.protected_target_bytes = min(
                self.capacity_bytes,
                self.protected_target_bytes + step,
            )

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            if not self._evict_one(evicted):
                break

        self.probation[key] = size
        self.used_bytes += size
        self._demote_protected()
        self._trim_ghosts()
        return evicted
