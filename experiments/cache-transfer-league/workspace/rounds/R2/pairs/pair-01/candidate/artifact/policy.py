from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0
        self.protected_target = self.capacity_bytes // 2
        self.step = max(1, self.capacity_bytes // 8)
        self.ghost_limit = 4096

    def _forget_ghost(self, key):
        self.ghost_probation.pop(key, None)
        self.ghost_protected.pop(key, None)

    def _remember_ghost(self, key, protected):
        self._forget_ghost(key)
        ghosts = self.ghost_protected if protected else self.ghost_probation
        ghosts[key] = None
        while len(ghosts) > self.ghost_limit:
            ghosts.popitem(last=False)

    def _demote(self):
        while len(self.protected) > 1 and self.protected_bytes > self.protected_target:
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
            self._demote()
            return []

        item_size = max(0, int(size))
        recent_ghost = key in self.ghost_probation
        protected_ghost = key in self.ghost_protected

        if item_size > self.capacity_bytes or self.capacity_bytes == 0:
            self._forget_ghost(key)
            return []

        if recent_ghost:
            self.protected_target = min(
                self.capacity_bytes, self.protected_target + self.step
            )
        elif protected_ghost:
            self.protected_target = max(0, self.protected_target - self.step)
        self._forget_ghost(key)
        self._demote()

        evicted = []
        while self.used_bytes + item_size > self.capacity_bytes:
            if self.probation:
                old_key, old_size = self.probation.popitem(last=False)
                self._remember_ghost(old_key, False)
            elif self.protected:
                old_key, old_size = self.protected.popitem(last=False)
                self.protected_bytes -= old_size
                self._remember_ghost(old_key, True)
            else:
                break
            self.used_bytes -= old_size
            evicted.append(old_key)

        if self.used_bytes + item_size <= self.capacity_bytes:
            self.probation[key] = item_size
            self.used_bytes += item_size
        return evicted
