from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.recent_ghost = OrderedDict()
        self.frequent_ghost = OrderedDict()
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.recent_ghost_bytes = 0
        self.frequent_ghost_bytes = 0
        self.used_bytes = 0
        self.protected_target = self.capacity_bytes // 2
        self.ghost_entry_limit = 4096

    def _forget_ghost(self, key):
        if key in self.recent_ghost:
            size = self.recent_ghost.pop(key)
            self.recent_ghost_bytes -= size
            return size, True
        if key in self.frequent_ghost:
            size = self.frequent_ghost.pop(key)
            self.frequent_ghost_bytes -= size
            return size, False
        return 0, None

    def _trim_ghosts(self):
        while self.recent_ghost and (
            self.recent_ghost_bytes > self.capacity_bytes
            or len(self.recent_ghost) + len(self.frequent_ghost) > self.ghost_entry_limit
        ):
            _, size = self.recent_ghost.popitem(last=False)
            self.recent_ghost_bytes -= size
        while self.frequent_ghost and (
            self.frequent_ghost_bytes > self.capacity_bytes
            or len(self.recent_ghost) + len(self.frequent_ghost) > self.ghost_entry_limit
        ):
            _, size = self.frequent_ghost.popitem(last=False)
            self.frequent_ghost_bytes -= size

    def _remember_recent(self, key, size):
        self._forget_ghost(key)
        self.recent_ghost[key] = size
        self.recent_ghost_bytes += size
        self._trim_ghosts()

    def _remember_frequent(self, key, size):
        self._forget_ghost(key)
        self.frequent_ghost[key] = size
        self.frequent_ghost_bytes += size
        self._trim_ghosts()

    def _demote_protected(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size
            self.probation_bytes += size

    def _evict_one(self):
        probation_limit = self.capacity_bytes - self.protected_target
        if self.probation and (
            self.probation_bytes > probation_limit or not self.protected
        ):
            key, size = self.probation.popitem(last=False)
            self.probation_bytes -= size
            self.used_bytes -= size
            self._remember_recent(key, size)
            return key
        if self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.used_bytes -= size
            self._remember_frequent(key, size)
            return key
        if self.probation:
            key, size = self.probation.popitem(last=False)
            self.probation_bytes -= size
            self.used_bytes -= size
            self._remember_recent(key, size)
            return key
        return None

    def access(self, key: int, size: int, now: int) -> list[int]:
        size = max(0, int(size))

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

        ghost_size, was_recent = self._forget_ghost(key)
        prefer_protected = was_recent is not None
        if was_recent is True:
            self.protected_target = min(
                self.capacity_bytes,
                self.protected_target + max(1, ghost_size),
            )
        elif was_recent is False:
            self.protected_target = max(
                0,
                self.protected_target - max(1, ghost_size),
            )
        self._demote_protected()

        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            victim = self._evict_one()
            if victim is None:
                break
            evicted.append(victim)

        if self.used_bytes + size > self.capacity_bytes:
            return evicted

        if prefer_protected:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.probation[key] = size
            self.probation_bytes += size
        self.used_bytes += size
        self._demote_protected()
        return evicted
