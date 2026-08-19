from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        self.capacity = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.used = 0
        self.target = self.capacity // 2
        self.ghost_bytes = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096
        self.serial = 0

    def _forget_ghost(self, key):
        value = self.ghost_probation.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]
        value = self.ghost_protected.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, kind):
        self._forget_ghost(key)
        self.serial += 1
        value = (max(1, int(size)), self.serial)
        if kind == 1:
            self.ghost_probation[key] = value
        else:
            self.ghost_protected[key] = value
        self.ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_probation) + len(self.ghost_protected) > self.ghost_count_limit):
            source = None
            oldest = None
            for ghosts in (self.ghost_probation, self.ghost_protected):
                if ghosts:
                    value = next(iter(ghosts.values()))
                    if oldest is None or value[1] < oldest[1]:
                        oldest = value
                        source = ghosts
            if source is None:
                return
            _, value = source.popitem(last=False)
            self.ghost_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        b1 = sum(value[0] for value in self.ghost_probation.values())
        b2 = sum(value[0] for value in self.ghost_protected.values())
        if kind == 1:
            delta = self.capacity if b1 == 0 else max(1, min(self.capacity, b2 // b1 or 1))
            self.target = min(self.capacity, self.target + delta)
        elif kind == 2:
            delta = self.capacity if b2 == 0 else max(1, min(self.capacity, b1 // b2 or 1))
            self.target = max(0, self.target - delta)

    def _remove_resident(self, key):
        value = self.probation.pop(key, None)
        if value is not None:
            self.probation_bytes -= value
            self.used -= value
            return 1, value
        value = self.protected.pop(key, None)
        if value is not None:
            self.protected_bytes -= value
            self.used -= value
            return 2, value
        return 0, None

    def _evict_one(self, prefer_probation):
        if self.probation and (prefer_probation or not self.protected):
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

    def _make_room(self, incoming, ghost_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            prefer_probation = self.probation_bytes >= self.target
            if ghost_kind == 1 and self.probation:
                prefer_probation = True
            elif ghost_kind == 2 and self.probation_bytes < self.target:
                prefer_probation = False
            key = self._evict_one(prefer_probation)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key, size, now):
        key = int(key)
        size = max(0, int(size))

        if key in self.probation or key in self.protected:
            self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            if self.used + size > self.capacity:
                return evicted + [key]
            self._forget_ghost(key)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            return evicted

        ghost_kind = 1 if key in self.ghost_probation else 2 if key in self.ghost_protected else 0
        if size <= 0 or size > self.capacity:
            return []
        if ghost_kind:
            self._adjust_target(ghost_kind)
            self._forget_ghost(key)

        evicted = self._make_room(size, ghost_kind)
        if self.used + size > self.capacity:
            return evicted
        if ghost_kind:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.probation[key] = size
            self.probation_bytes += size
        self.used += size
        return evicted
