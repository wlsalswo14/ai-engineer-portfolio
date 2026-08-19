from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        self.capacity = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.ghost_recent_bytes = 0
        self.ghost_protected_bytes = 0
        self.used = 0
        self.target = self.capacity // 2
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096
        self.serial = 0

    def _drop_ghost(self, key):
        value = self.ghost_recent.pop(key, None)
        if value is not None:
            self.ghost_recent_bytes -= value[0]
        value = self.ghost_protected.pop(key, None)
        if value is not None:
            self.ghost_protected_bytes -= value[0]

    def _remember_ghost(self, key, size, protected):
        self._drop_ghost(key)
        self.serial += 1
        value = (max(1, int(size)), self.serial)
        if protected:
            self.ghost_protected[key] = value
            self.ghost_protected_bytes += value[0]
        else:
            self.ghost_recent[key] = value
            self.ghost_recent_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_recent_bytes + self.ghost_protected_bytes > self.ghost_limit or
               len(self.ghost_recent) + len(self.ghost_protected) > self.ghost_count_limit):
            source = None
            oldest = None
            for candidate in (self.ghost_recent, self.ghost_protected):
                if candidate:
                    value = next(iter(candidate.values()))
                    if oldest is None or value[1] < oldest[1]:
                        source = candidate
                        oldest = value
            _, value = source.popitem(last=False)
            if source is self.ghost_recent:
                self.ghost_recent_bytes -= value[0]
            else:
                self.ghost_protected_bytes -= value[0]

    def _adjust_target(self, recent_ghost):
        if self.capacity <= 0:
            return
        recent = self.ghost_recent_bytes
        protected = self.ghost_protected_bytes
        if recent_ghost:
            delta = self.capacity if recent == 0 else max(1, min(self.capacity, protected // recent or 1))
            self.target = min(self.capacity, self.target + delta)
        else:
            delta = self.capacity if protected == 0 else max(1, min(self.capacity, recent // protected or 1))
            self.target = max(0, self.target - delta)

    def _remove_resident(self, key):
        value = self.probation.pop(key, None)
        if value is not None:
            self.probation_bytes -= value
            self.used -= value
            return value
        value = self.protected.pop(key, None)
        if value is not None:
            self.protected_bytes -= value
            self.used -= value
            return value
        return None

    def _replace_one(self, from_protected_ghost):
        choose_probation = bool(self.probation) and (
            self.probation_bytes > self.target or
            (from_protected_ghost and self.probation_bytes == self.target)
        )
        if choose_probation or not self.protected:
            if self.probation:
                key, size = self.probation.popitem(last=False)
                self.probation_bytes -= size
                self.used -= size
                self._remember_ghost(key, size, False)
                return key
        if self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, True)
            return key
        if self.probation:
            key, size = self.probation.popitem(last=False)
            self.probation_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, False)
            return key
        return None

    def _make_room(self, incoming, from_protected_ghost):
        evicted = []
        while self.used + incoming > self.capacity:
            key = self._replace_one(from_protected_ghost)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key, size, now):
        key = int(key)
        size = max(0, int(size))
        _ = now

        if key in self.probation or key in self.protected:
            self._remove_resident(key)
            self._drop_ghost(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, False)
            if self.used + size > self.capacity:
                return evicted + [key]
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            return evicted

        recent_ghost = key in self.ghost_recent
        protected_ghost = key in self.ghost_protected
        if size <= 0 or size > self.capacity:
            if recent_ghost or protected_ghost:
                self._drop_ghost(key)
            return []

        from_protected_ghost = protected_ghost and not recent_ghost
        if recent_ghost or protected_ghost:
            self._adjust_target(recent_ghost)
            self._drop_ghost(key)

        evicted = self._make_room(size, from_protected_ghost)
        if self.used + size > self.capacity:
            return evicted
        self.probation[key] = size
        self.probation_bytes += size
        self.used += size
        return evicted
