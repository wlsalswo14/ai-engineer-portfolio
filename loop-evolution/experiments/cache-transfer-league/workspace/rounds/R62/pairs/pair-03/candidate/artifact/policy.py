from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.probation_ghost = OrderedDict()
        self.protected_ghost = OrderedDict()
        self.ghost_limit = 4096
        self.probation_target = self.capacity_bytes // 2
        self.probation_bytes = 0
        self.protected_bytes = 0
        self._counter = {}
        self._clock = 0
        self._aperture_width = 4

    def _forget_ghost(self, key):
        self.probation_ghost.pop(key, None)
        self.protected_ghost.pop(key, None)

    def _remember_ghost(self, ghost, key, size):
        self._forget_ghost(key)
        ghost[key] = size
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _touch(self, key):
        self._clock += 1
        self._counter[key] = self._counter.get(key, 0) + 1

    def _take(self, key):
        if key in self.probation:
            size = self.probation.pop(key)
            self.probation_bytes -= size
            return size, 1
        if key in self.protected:
            size = self.protected.pop(key)
            self.protected_bytes -= size
            return size, 2
        return None, None

    def _pick_terminal(self, segment):
        if not segment:
            return None, None
        candidates = []
        for key, size in list(segment.items())[:self._aperture_width]:
            candidates.append((self._counter.get(key, 1), key, size))
        _, key, size = min(candidates, key=lambda item: (item[0], list(segment).index(item[1])))
        segment.pop(key)
        return key, size

    def _replace(self, protected_ghost_hit):
        use_probation = bool(self.probation) and (
            self.probation_bytes > self.probation_target
            or (protected_ghost_hit and self.probation_bytes == self.probation_target)
        )
        if use_probation:
            key, size = self._pick_terminal(self.probation)
            self.probation_bytes -= size
            self._remember_ghost(self.probation_ghost, key, size)
            self._counter.pop(key, None)
            return key
        if self.protected:
            key, size = self._pick_terminal(self.protected)
            self.protected_bytes -= size
            self._remember_ghost(self.protected_ghost, key, size)
            self._counter.pop(key, None)
            return key
        if self.probation:
            key, size = self._pick_terminal(self.probation)
            self.probation_bytes -= size
            self._remember_ghost(self.probation_ghost, key, size)
            self._counter.pop(key, None)
            return key
        return None

    def _make_room(self, size, protected_ghost_hit):
        evicted = []
        while self.probation_bytes + self.protected_bytes + size > self.capacity_bytes:
            key = self._replace(protected_ghost_hit)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        requested = int(size)

        if requested <= 0:
            if key in self.probation:
                self.probation.move_to_end(key)
                self._touch(key)
            elif key in self.protected:
                self.protected.move_to_end(key)
                self._touch(key)
            return []

        if requested > self.capacity_bytes:
            old_size, segment = self._take(key)
            if segment == 1:
                self._remember_ghost(self.probation_ghost, key, old_size)
                self._counter.pop(key, None)
                return [key]
            if segment == 2:
                self._remember_ghost(self.protected_ghost, key, old_size)
                self._counter.pop(key, None)
                return [key]
            return []

        if key in self.probation:
            old_size, _ = self._take(key)
            evicted = self._make_room(requested, False)
            self.protected[key] = requested
            self.protected_bytes += requested
            self._counter[key] = self._counter.get(key, 1) + 1
            return evicted

        if key in self.protected:
            self._take(key)
            evicted = self._make_room(requested, False)
            self.protected[key] = requested
            self.protected_bytes += requested
            self._touch(key)
            return evicted

        probation_ghost_hit = key in self.probation_ghost
        protected_ghost_hit = key in self.protected_ghost

        if probation_ghost_hit:
            step = max(1, self.capacity_bytes // 16)
            self.probation_target = min(
                self.capacity_bytes,
                self.probation_target + max(step, min(requested, self.capacity_bytes)),
            )
        elif protected_ghost_hit:
            step = max(1, self.capacity_bytes // 16)
            self.probation_target = max(
                0,
                self.probation_target - max(step, min(requested, self.capacity_bytes)),
            )

        self._forget_ghost(key)
        evicted = self._make_room(requested, protected_ghost_hit)

        self._counter[key] = 1
        if probation_ghost_hit or protected_ghost_hit:
            self.protected[key] = requested
            self.protected_bytes += requested
        else:
            self.probation[key] = requested
            self.probation_bytes += requested
        return evicted
