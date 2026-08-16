from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.target = self.capacity_bytes // 2
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.ghost_probation_bytes = 0
        self.ghost_protected_bytes = 0
        self.used_bytes = 0
        self.ghost_limit = 4096
        self.ghost_byte_limit = max(1, self.capacity_bytes * 2)
        self.intervention_grounded = False
        self.sensitivity_events = 0

    def _forget_ghost(self, key):
        size = self.ghost_probation.pop(key, None)
        if size is not None:
            self.ghost_probation_bytes -= size
        size = self.ghost_protected.pop(key, None)
        if size is not None:
            self.ghost_protected_bytes -= size

    def _remember_ghost(self, ghost, key, size):
        self._forget_ghost(key)
        ghost[key] = size
        if ghost is self.ghost_probation:
            self.ghost_probation_bytes += size
        else:
            self.ghost_protected_bytes += size
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (len(self.ghost_probation) > self.ghost_limit or
               self.ghost_probation_bytes > self.ghost_byte_limit):
            _, size = self.ghost_probation.popitem(last=False)
            self.ghost_probation_bytes -= size
        while (len(self.ghost_protected) > self.ghost_limit or
               self.ghost_protected_bytes > self.ghost_byte_limit):
            _, size = self.ghost_protected.popitem(last=False)
            self.ghost_protected_bytes -= size

    def _dependency_source(self, key):
        if key in self.ghost_probation:
            return 1
        if key in self.ghost_protected:
            return 2
        return 0

    def _adjust_target(self, source, size):
        if not source or self.capacity_bytes <= 0:
            return
        self.intervention_grounded = True
        self.sensitivity_events += 1
        weight = max(1, min(self.capacity_bytes, size))
        if source == 1:
            ratio = max(
                1,
                self.ghost_protected_bytes // max(1, self.ghost_probation_bytes),
            )
            delta = min(self.capacity_bytes, weight * ratio)
            self.target = min(self.capacity_bytes, self.target + delta)
        else:
            ratio = max(
                1,
                self.ghost_probation_bytes // max(1, self.ghost_protected_bytes),
            )
            delta = min(self.capacity_bytes, weight * ratio)
            self.target = max(0, self.target - delta)

    def _evict_one(self, incoming_from_protected_ghost):
        choose_probation = bool(self.probation) and (
            self.probation_bytes > self.target or
            (incoming_from_protected_ghost and
             self.probation_bytes == self.target)
        )
        if choose_probation or not self.protected:
            if not self.probation:
                return None
            key, size = self.probation.popitem(last=False)
            self.probation_bytes -= size
            self.used_bytes -= size
            self._remember_ghost(self.ghost_probation, key, size)
            return key
        key, size = self.protected.popitem(last=False)
        self.protected_bytes -= size
        self.used_bytes -= size
        self._remember_ghost(self.ghost_protected, key, size)
        return key

    def _make_room(self, size, incoming_from_protected_ghost):
        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            key = self._evict_one(incoming_from_protected_ghost)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def _insert(self, table, key, size):
        table[key] = size
        if table is self.probation:
            self.probation_bytes += size
        else:
            self.protected_bytes += size
        self.used_bytes += size

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.probation_bytes -= stored_size
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            return []

        if self.capacity_bytes == 0 or size <= 0 or size > self.capacity_bytes:
            return []

        source = self._dependency_source(key)
        self._adjust_target(source, size)
        self._forget_ghost(key)

        incoming_from_protected_ghost = source == 2
        evicted = self._make_room(size, incoming_from_protected_ghost)

        if incoming_from_protected_ghost and self.intervention_grounded:
            self._insert(self.protected, key, size)
        else:
            self._insert(self.probation, key, size)
        return evicted
