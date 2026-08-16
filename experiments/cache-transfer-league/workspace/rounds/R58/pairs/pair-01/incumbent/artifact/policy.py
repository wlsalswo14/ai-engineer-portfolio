from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.ghost_limit = 4096
        self.target = self.capacity_bytes // 2
        self.probation_bytes = 0
        self.protected_bytes = 0

    def _forget_ghost(self, key):
        self.ghost_probation.pop(key, None)
        self.ghost_protected.pop(key, None)

    def _remember(self, ghost, key, size):
        self._forget_ghost(key)
        ghost[key] = size
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _take_active(self, key):
        if key in self.probation:
            size = self.probation.pop(key)
            self.probation_bytes -= size
            return size, 1
        if key in self.protected:
            size = self.protected.pop(key)
            self.protected_bytes -= size
            return size, 2
        return None, None

    def _evict_one(self, protected_ghost_hit):
        use_probation = bool(self.probation) and (
            self.probation_bytes > self.target
            or (protected_ghost_hit and self.probation_bytes == self.target)
        )
        if use_probation:
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

    def _make_room(self, size, protected_ghost_hit):
        evicted = []
        while (
            self.probation_bytes + self.protected_bytes + size
            > self.capacity_bytes
        ):
            victim = self._evict_one(protected_ghost_hit)
            if victim is None:
                break
            evicted.append(victim)
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
            old_size, segment = self._take_active(key)
            if segment == 1:
                self._remember(self.ghost_probation, key, old_size)
                return [key]
            if segment == 2:
                self._remember(self.ghost_protected, key, old_size)
                return [key]
            return []

        if key in self.probation:
            self._take_active(key)
            evicted = self._make_room(requested, False)
            self._forget_ghost(key)
            self.protected[key] = requested
            self.protected_bytes += requested
            return evicted

        if key in self.protected:
            self._take_active(key)
            evicted = self._make_room(requested, False)
            self._forget_ghost(key)
            self.protected[key] = requested
            self.protected_bytes += requested
            return evicted

        probation_ghost_hit = key in self.ghost_probation
        protected_ghost_hit = key in self.ghost_protected
        step = max(1, self.capacity_bytes // 16)

        if probation_ghost_hit:
            self.target = min(
                self.capacity_bytes,
                self.target + max(step, min(requested, self.capacity_bytes)),
            )
        elif protected_ghost_hit:
            self.target = max(
                0,
                self.target - max(step, min(requested, self.capacity_bytes)),
            )

        self._forget_ghost(key)
        evicted = self._make_room(requested, protected_ghost_hit)

        if probation_ghost_hit or protected_ghost_hit:
            self.protected[key] = requested
            self.protected_bytes += requested
        else:
            self.probation[key] = requested
            self.probation_bytes += requested

        return evicted
