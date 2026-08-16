from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.target = self.capacity_bytes // 2
        self.ghost_limit = max(64, min(8192, self.capacity_bytes // 64 + 64))

    def _forget_ghost(self, key):
        self.ghost_probation.pop(key, None)
        self.ghost_protected.pop(key, None)

    def _remember(self, ghost, key, size):
        self._forget_ghost(key)
        ghost[key] = size
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _remove_resident(self, key):
        if key in self.probation:
            size = self.probation.pop(key)
            self.probation_bytes -= size
            return size, 1
        if key in self.protected:
            size = self.protected.pop(key)
            self.protected_bytes -= size
            return size, 2
        return None, None

    def _evict_one(self, protected_hit):
        if protected_hit and self.probation:
            key, size = self.probation.popitem(last=False)
            self.probation_bytes -= size
            self._remember(self.ghost_probation, key, size)
            return key

        choose_probation = bool(self.probation) and self.probation_bytes > self.target
        if choose_probation:
            key, size = self.probation.popitem(last=False)
            self.probation_bytes -= size
            self._remember(self.ghost_probation, key, size)
            return key

        if self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self._remember(self.ghost_protected, key, size)
            return key

        if self.probation:
            key, size = self.probation.popitem(last=False)
            self.probation_bytes -= size
            self._remember(self.ghost_probation, key, size)
            return key

        return None

    def _make_room(self, incoming, protected_hit):
        evicted = []
        while self.probation_bytes + self.protected_bytes + incoming > self.capacity_bytes:
            key = self._evict_one(protected_hit)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        requested = int(size)

        if requested <= 0:
            if key in self.probation:
                self.probation.move_to_end(key)
            elif key in self.protected:
                self.protected.move_to_end(key)
            return []

        if requested > self.capacity_bytes:
            old_size, segment = self._remove_resident(key)
            if segment == 1:
                self._remember(self.ghost_probation, key, old_size)
                return [key]
            if segment == 2:
                self._remember(self.ghost_protected, key, old_size)
                return [key]
            return []

        old_size, segment = self._remove_resident(key)
        if segment is not None:
            evicted = self._make_room(requested, False)
            self._forget_ghost(key)
            self.protected[key] = requested
            self.protected_bytes += requested
            return evicted

        probation_hit = key in self.ghost_probation
        protected_hit = key in self.ghost_protected

        if probation_hit:
            step = max(1, self.capacity_bytes // 16)
            self.target = min(
                self.capacity_bytes,
                self.target + max(step, min(requested, self.capacity_bytes)),
            )
        elif protected_hit:
            step = max(1, self.capacity_bytes // 16)
            self.target = max(
                0,
                self.target - max(step, min(requested, self.capacity_bytes)),
            )

        evicted = self._make_room(requested, protected_hit)
        self._forget_ghost(key)

        if probation_hit or protected_hit:
            self.protected[key] = requested
            self.protected_bytes += requested
        else:
            self.probation[key] = requested
            self.probation_bytes += requested

        return evicted
