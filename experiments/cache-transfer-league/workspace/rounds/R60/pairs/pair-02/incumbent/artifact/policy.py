from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.ghost_limit = 4096
        self.probation_target = self.capacity_bytes // 2
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

    def _take(self, key):
        if key in self.probation:
            size = self.probation.pop(key)
            self.probation_bytes -= size
            return size, 1
        if key in self.protected:
            size = self.protected.pop(key)
            self.protected_bytes -= size
            return size, 2
        return None

    def _evict_one(self, favor_probation):
        use_probation = bool(self.probation) and (
            self.probation_bytes > self.probation_target
            or (favor_probation and self.probation_bytes == self.probation_target)
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

    def _make_room(self, size, favor_probation):
        evicted = []
        while self.probation_bytes + self.protected_bytes + size > self.capacity_bytes:
            key = self._evict_one(favor_probation)
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
            removed = self._take(key)
            if removed is None:
                self._forget_ghost(key)
                return []
            old_size, segment = removed
            if segment == 1:
                self._remember(self.ghost_probation, key, old_size)
            else:
                self._remember(self.ghost_protected, key, old_size)
            return [key]

        if key in self.probation:
            self._take(key)
            evicted = self._make_room(requested, False)
            self._forget_ghost(key)
            self.protected[key] = requested
            self.protected_bytes += requested
            return evicted

        if key in self.protected:
            self._take(key)
            evicted = self._make_room(requested, False)
            self._forget_ghost(key)
            self.protected[key] = requested
            self.protected_bytes += requested
            return evicted

        probation_hit = key in self.ghost_probation
        protected_hit = key in self.ghost_protected
        if probation_hit:
            step = max(1, self.capacity_bytes // 16)
            self.probation_target = min(
                self.capacity_bytes,
                self.probation_target + max(step, min(requested, self.capacity_bytes)),
            )
        elif protected_hit:
            step = max(1, self.capacity_bytes // 16)
            self.probation_target = max(
                0,
                self.probation_target - max(step, min(requested, self.capacity_bytes)),
            )

        self._forget_ghost(key)
        evicted = self._make_room(requested, probation_hit)
        if probation_hit or protected_hit:
            self.protected[key] = requested
            self.protected_bytes += requested
        else:
            self.probation[key] = requested
            self.probation_bytes += requested
        return evicted
