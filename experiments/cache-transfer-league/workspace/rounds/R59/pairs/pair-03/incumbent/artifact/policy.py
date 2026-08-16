from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probationary = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probationary = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.ghost_limit = 4096
        self.target_bytes = self.capacity_bytes // 2
        self.probationary_bytes = 0
        self.protected_bytes = 0

    def _discard_ghost(self, key):
        self.ghost_probationary.pop(key, None)
        self.ghost_protected.pop(key, None)

    def _remember(self, ghost, key, size):
        self._discard_ghost(key)
        ghost[key] = int(size)
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _remove_resident(self, key):
        if key in self.probationary:
            size = self.probationary.pop(key)
            self.probationary_bytes -= size
            return size, 1
        if key in self.protected:
            size = self.protected.pop(key)
            self.protected_bytes -= size
            return size, 2
        return None, None

    def _replace_one(self, protected_ghost_hit):
        use_probationary = bool(self.probationary) and (
            self.probationary_bytes > self.target_bytes
            or (protected_ghost_hit and self.probationary_bytes == self.target_bytes)
        )
        if use_probationary:
            key, size = self.probationary.popitem(last=False)
            self.probationary_bytes -= size
            self._remember(self.ghost_probationary, key, size)
            return key
        if self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self._remember(self.ghost_protected, key, size)
            return key
        if self.probationary:
            key, size = self.probationary.popitem(last=False)
            self.probationary_bytes -= size
            self._remember(self.ghost_probationary, key, size)
            return key
        return None

    def _make_room(self, size, protected_ghost_hit):
        evicted = []
        while self.probationary_bytes + self.protected_bytes + size > self.capacity_bytes:
            key = self._replace_one(protected_ghost_hit)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def _adaptation_step(self, requested):
        bound = max(1, self.capacity_bytes // 8)
        return max(1, min(bound, requested))

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        requested = int(size)

        if requested <= 0:
            if key in self.probationary:
                self.probationary.move_to_end(key)
            elif key in self.protected:
                self.protected.move_to_end(key)
            return []

        if requested > self.capacity_bytes:
            old_size, segment = self._remove_resident(key)
            if segment == 1:
                self._remember(self.ghost_probationary, key, old_size)
                return [key]
            if segment == 2:
                self._remember(self.ghost_protected, key, old_size)
                return [key]
            return []

        if key in self.probationary:
            self._remove_resident(key)
            evicted = self._make_room(requested, False)
            self.protected[key] = requested
            self.protected_bytes += requested
            return evicted

        if key in self.protected:
            self._remove_resident(key)
            evicted = self._make_room(requested, False)
            self.protected[key] = requested
            self.protected_bytes += requested
            return evicted

        probationary_ghost_hit = key in self.ghost_probationary
        protected_ghost_hit = key in self.ghost_protected
        if probationary_ghost_hit:
            old_size = self.ghost_probationary[key]
            self.target_bytes = min(
                self.capacity_bytes,
                self.target_bytes + self._adaptation_step(max(requested, old_size)),
            )
        elif protected_ghost_hit:
            old_size = self.ghost_protected[key]
            self.target_bytes = max(
                0,
                self.target_bytes - self._adaptation_step(max(requested, old_size)),
            )

        self._discard_ghost(key)
        evicted = self._make_room(requested, protected_ghost_hit)
        if probationary_ghost_hit or protected_ghost_hit:
            self.protected[key] = requested
            self.protected_bytes += requested
        else:
            self.probationary[key] = requested
            self.probationary_bytes += requested
        return evicted
