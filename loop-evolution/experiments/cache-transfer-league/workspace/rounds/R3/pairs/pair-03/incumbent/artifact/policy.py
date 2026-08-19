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
        self.ghost_probation_bytes = 0
        self.ghost_protected_bytes = 0
        self.used_bytes = 0
        self.target_probation = self.capacity_bytes // 2

    def _remove_ghost(self, queue, key, protected):
        if key not in queue:
            return 0
        size = queue.pop(key)
        if protected:
            self.ghost_protected_bytes -= size
        else:
            self.ghost_probation_bytes -= size
        return size

    def _remember(self, key, size, protected):
        self._remove_ghost(self.ghost_probation, key, False)
        self._remove_ghost(self.ghost_protected, key, True)
        queue = self.ghost_protected if protected else self.ghost_probation
        queue[key] = size
        if protected:
            self.ghost_protected_bytes += size
        else:
            self.ghost_probation_bytes += size
        self._trim_ghosts()

    def _trim_ghosts(self):
        limit = self.capacity_bytes
        while self.ghost_probation_bytes + self.ghost_protected_bytes > limit:
            if self.ghost_probation:
                key, size = self.ghost_probation.popitem(last=False)
                self.ghost_probation_bytes -= size
            elif self.ghost_protected:
                key, size = self.ghost_protected.popitem(last=False)
                self.ghost_protected_bytes -= size
            else:
                break

    def _make_room(self, incoming, evicted):
        while self.used_bytes + incoming > self.capacity_bytes:
            take_probation = bool(self.probation) and (
                self.probation_bytes > self.target_probation
                or not self.protected
            )
            if take_probation:
                key, size = self.probation.popitem(last=False)
                self.probation_bytes -= size
                self.used_bytes -= size
                self._remember(key, size, False)
                evicted.append(key)
            elif self.protected:
                key, size = self.protected.popitem(last=False)
                self.protected_bytes -= size
                self.used_bytes -= size
                self._remember(key, size, True)
                evicted.append(key)
            elif self.probation:
                key, size = self.probation.popitem(last=False)
                self.probation_bytes -= size
                self.used_bytes -= size
                self._remember(key, size, False)
                evicted.append(key)
            else:
                break
        return self.used_bytes + incoming <= self.capacity_bytes

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

        if size < 0 or self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        evicted = []

        if key in self.ghost_probation:
            base = max(1, self.ghost_probation_bytes)
            delta = max(1, self.ghost_protected_bytes // base)
            self._remove_ghost(self.ghost_probation, key, False)
            self.target_probation = min(self.capacity_bytes, self.target_probation + delta)
            if not self._make_room(size, evicted):
                return evicted
            self.protected[key] = size
            self.protected_bytes += size
            self.used_bytes += size
            return evicted

        if key in self.ghost_protected:
            base = max(1, self.ghost_protected_bytes)
            delta = max(1, self.ghost_probation_bytes // base)
            self._remove_ghost(self.ghost_protected, key, True)
            self.target_probation = max(0, self.target_probation - delta)
            if not self._make_room(size, evicted):
                return evicted
            self.protected[key] = size
            self.protected_bytes += size
            self.used_bytes += size
            return evicted

        if not self._make_room(size, evicted):
            return evicted
        self.probation[key] = size
        self.probation_bytes += size
        self.used_bytes += size
        return evicted
