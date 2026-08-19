from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.used = 0
        self.probation_target = self.capacity // 2
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.ghost_bytes = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096
        self.serial = 0

    def _drop_ghost(self, key):
        value = self.ghost_probation.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]
        value = self.ghost_protected.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, kind):
        self._drop_ghost(key)
        self.serial += 1
        value = (size, self.serial)
        if kind == 1:
            self.ghost_probation[key] = value
        else:
            self.ghost_protected[key] = value
        self.ghost_bytes += size
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_probation) + len(self.ghost_protected) > self.ghost_count_limit):
            kind = 0
            oldest = None
            if self.ghost_probation:
                kind = 1
                oldest = next(iter(self.ghost_probation.values()))[1]
            if self.ghost_protected:
                other = next(iter(self.ghost_protected.values()))[1]
                if oldest is None or other < oldest:
                    kind = 2
            ghosts = self.ghost_probation if kind == 1 else self.ghost_protected
            _, value = ghosts.popitem(last=False)
            self.ghost_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        b1 = sum(value[0] for value in self.ghost_probation.values())
        b2 = sum(value[0] for value in self.ghost_protected.values())
        if kind == 1:
            delta = self.capacity if b1 == 0 else max(1, min(self.capacity, b2 // b1 or 1))
            self.probation_target = min(self.capacity, self.probation_target + delta)
        else:
            delta = self.capacity if b2 == 0 else max(1, min(self.capacity, b1 // b2 or 1))
            self.probation_target = max(0, self.probation_target - delta)

    def _remove_resident(self, key):
        value = self.probation.pop(key, None)
        if value is not None:
            self.probation_bytes -= value
            self.used -= value
            return value, 1
        value = self.protected.pop(key, None)
        if value is not None:
            self.protected_bytes -= value
            self.used -= value
            return value, 2
        return 0, 0

    def _demote_if_needed(self):
        protected_limit = self.capacity - self.probation_target
        while self.protected and self.protected_bytes > protected_limit:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size
            self.probation_bytes += size

    def _evict_one(self, prefer_probation):
        if prefer_probation and self.probation:
            key, size = self.probation.popitem(last=False)
            self.probation_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 1)
            return key
        if self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 2)
            return key
        if self.probation:
            key, size = self.probation.popitem(last=False)
            self.probation_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 1)
            return key
        return None

    def _make_room(self, incoming):
        evicted = []
        self._demote_if_needed()
        while self.used + incoming > self.capacity:
            prefer_probation = bool(self.probation) and (
                self.probation_bytes > self.probation_target or not self.protected
            )
            key = self._evict_one(prefer_probation)
            if key is None:
                break
            evicted.append(key)
            self._demote_if_needed()
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))

        if key in self.probation or key in self.protected:
            self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            self._demote_if_needed()
            return evicted

        kind = 1 if key in self.ghost_probation else 2 if key in self.ghost_protected else 0
        if kind:
            self._adjust_target(kind)
            self._drop_ghost(key)

        if size <= 0 or size > self.capacity:
            return []

        evicted = self._make_room(size)
        if kind == 2 or kind == 1:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.probation[key] = size
            self.probation_bytes += size
        self.used += size
        self._demote_if_needed()
        return evicted
