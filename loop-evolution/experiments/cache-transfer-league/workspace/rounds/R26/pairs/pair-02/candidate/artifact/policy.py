from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.used_bytes = 0
        self.protected_target = self.capacity_bytes // 2
        self.ghost_probation_bytes = 0
        self.ghost_protected_bytes = 0
        self.ghost_limit = max(64, min(4096, self.capacity_bytes * 2))
        self.ghost_serial = 0

    def _forget_ghost(self, key):
        entry = self.ghost_probation.pop(key, None)
        if entry is not None:
            self.ghost_probation_bytes -= entry[0]
        entry = self.ghost_protected.pop(key, None)
        if entry is not None:
            self.ghost_protected_bytes -= entry[0]

    def _trim_ghosts(self):
        while (self.ghost_probation_bytes + self.ghost_protected_bytes
               > self.ghost_limit):
            if not self.ghost_probation:
                ghost = self.ghost_protected
                is_probation = False
            elif not self.ghost_protected:
                ghost = self.ghost_probation
                is_probation = True
            else:
                p_first = next(iter(self.ghost_probation.values()))
                q_first = next(iter(self.ghost_protected.values()))
                if p_first[1] <= q_first[1]:
                    ghost = self.ghost_probation
                    is_probation = True
                else:
                    ghost = self.ghost_protected
                    is_probation = False
            _, entry = ghost.popitem(last=False)
            if is_probation:
                self.ghost_probation_bytes -= entry[0]
            else:
                self.ghost_protected_bytes -= entry[0]

    def _remember(self, ghost, key, size):
        self._forget_ghost(key)
        self.ghost_serial += 1
        ghost[key] = (size, self.ghost_serial)
        if ghost is self.ghost_probation:
            self.ghost_probation_bytes += size
        else:
            self.ghost_protected_bytes += size
        self._trim_ghosts()

    def _replace_one(self, from_ghost_protected):
        choose_probation = (
            bool(self.probation)
            and (self.probation_bytes > self.protected_target
                 or (from_ghost_protected
                     and self.probation_bytes == self.protected_target)
                 or not self.protected)
        )
        if choose_probation:
            key, size = self.probation.popitem(last=False)
            self.probation_bytes -= size
            self.used_bytes -= size
            self._remember(self.ghost_probation, key, size)
            return key
        if self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.used_bytes -= size
            self._remember(self.ghost_protected, key, size)
            return key
        if self.probation:
            key, size = self.probation.popitem(last=False)
            self.probation_bytes -= size
            self.used_bytes -= size
            self._remember(self.ghost_probation, key, size)
            return key
        return None

    def _make_room(self, size, from_ghost_protected):
        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            key = self._replace_one(from_ghost_protected)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.probation:
            old_size = self.probation[key]
            if size <= 0 or size > self.capacity_bytes:
                return []
            self.probation.pop(key)
            self.probation_bytes -= old_size
            self.used_bytes -= old_size
            evicted = self._make_room(size, False)
            if self.used_bytes + size > self.capacity_bytes:
                self.probation[key] = old_size
                self.probation_bytes += old_size
                self.used_bytes += old_size
                return evicted
            self.protected[key] = size
            self.protected_bytes += size
            self.used_bytes += size
            return evicted

        if key in self.protected:
            old_size = self.protected[key]
            if size <= 0 or size > self.capacity_bytes:
                return []
            self.protected.pop(key)
            self.protected_bytes -= old_size
            self.used_bytes -= old_size
            evicted = self._make_room(size, False)
            if self.used_bytes + size > self.capacity_bytes:
                self.protected[key] = old_size
                self.protected_bytes += old_size
                self.used_bytes += old_size
                return evicted
            self.protected[key] = size
            self.protected_bytes += size
            self.used_bytes += size
            return evicted

        if size <= 0 or size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        from_ghost_protected = key in self.ghost_protected
        step = max(1, self.capacity_bytes // 16)
        delta = max(step, min(size, self.capacity_bytes))
        if key in self.ghost_probation:
            self.protected_target = min(
                self.capacity_bytes, self.protected_target + delta
            )
        elif from_ghost_protected:
            self.protected_target = max(
                0, self.protected_target - delta
            )
        self._forget_ghost(key)

        evicted = self._make_room(size, from_ghost_protected)
        if self.used_bytes + size > self.capacity_bytes:
            return evicted
        self.probation[key] = size
        self.probation_bytes += size
        self.used_bytes += size
        return evicted
