from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.protected_target = self.capacity_bytes // 2
        self.protected_bytes = 0
        self.used_bytes = 0
        self.ghost_probation_bytes = 0
        self.ghost_protected_bytes = 0

    def _forget_ghost(self, key):
        size = self.ghost_probation.pop(key, None)
        if size is not None:
            self.ghost_probation_bytes -= size
            return 'probation', size
        size = self.ghost_protected.pop(key, None)
        if size is not None:
            self.ghost_protected_bytes -= size
            return 'protected', size
        return None, None

    def _remember_ghost(self, segment, key, size):
        if segment == 'probation':
            ghost = self.ghost_probation
            other = self.ghost_protected
            other_size = self.ghost_protected_bytes
            if key in other:
                other_size -= other.pop(key)
                self.ghost_protected_bytes = other_size
            if key in ghost:
                self.ghost_probation_bytes -= ghost.pop(key)
            ghost[key] = size
            self.ghost_probation_bytes += size
            while ghost and self.ghost_probation_bytes > self.capacity_bytes:
                old_key, old_size = ghost.popitem(last=False)
                self.ghost_probation_bytes -= old_size
        else:
            ghost = self.ghost_protected
            other = self.ghost_probation
            other_size = self.ghost_probation_bytes
            if key in other:
                other_size -= other.pop(key)
                self.ghost_probation_bytes = other_size
            if key in ghost:
                self.ghost_protected_bytes -= ghost.pop(key)
            ghost[key] = size
            self.ghost_protected_bytes += size
            while ghost and self.ghost_protected_bytes > self.capacity_bytes:
                old_key, old_size = ghost.popitem(last=False)
                self.ghost_protected_bytes -= old_size

    def _demote_protected(self):
        while self.protected and self.protected_bytes > self.protected_target:
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

        if size < 0 or size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        origin, remembered_size = self._forget_ghost(key)
        if origin == 'probation':
            self.protected_target = min(
                self.capacity_bytes,
                self.protected_target + max(1, remembered_size),
            )
        elif origin == 'protected':
            self.protected_target = max(
                0,
                self.protected_target - max(1, remembered_size),
            )
        self._demote_protected()

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            if self.probation:
                old_key, old_size = self.probation.popitem(last=False)
                self._remember_ghost('probation', old_key, old_size)
            elif self.protected:
                old_key, old_size = self.protected.popitem(last=False)
                self.protected_bytes -= old_size
                self._remember_ghost('protected', old_key, old_size)
            else:
                break
            self.used_bytes -= old_size
            evicted.append(old_key)

        self.probation[key] = size
        self.used_bytes += size
        return evicted
