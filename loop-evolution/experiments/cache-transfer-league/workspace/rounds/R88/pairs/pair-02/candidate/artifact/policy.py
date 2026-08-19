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
        self.serial = 0
        self.ghost_bytes = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096

    def _drop_ghost(self, key):
        value = self.ghost_probation.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]
        value = self.ghost_protected.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, protected):
        self._drop_ghost(key)
        self.serial += 1
        value = (max(0, int(size)), self.serial)
        if protected:
            self.ghost_protected[key] = value
        else:
            self.ghost_probation[key] = value
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
            _, value = source.popitem(last=False)
            self.ghost_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        first = sum(value[0] for value in self.ghost_probation.values())
        second = sum(value[0] for value in self.ghost_protected.values())
        if kind == 1:
            delta = self.capacity if first == 0 else max(1, min(self.capacity, second // first or 1))
            self.target = min(self.capacity, self.target + delta)
        else:
            delta = self.capacity if second == 0 else max(1, min(self.capacity, first // second or 1))
            self.target = max(0, self.target - delta)

    def _remove_resident(self, key):
        value = self.probation.pop(key, None)
        if value is not None:
            self.probation_bytes -= value
            self.used -= value
            return value, False
        value = self.protected.pop(key, None)
        if value is not None:
            self.protected_bytes -= value
            self.used -= value
            return value, True
        return None

    def _evict_one(self, prefer_probation):
        if prefer_probation and self.probation:
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

    def _make_room(self, incoming, ghost_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            if ghost_kind == 1:
                prefer_probation = self.probation_bytes >= self.target
            elif ghost_kind == 2:
                prefer_probation = self.probation_bytes > self.target
            else:
                prefer_probation = self.probation_bytes > self.target or not self.protected
            key = self._evict_one(prefer_probation)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key, size, now):
        key = int(key)
        size = max(0, int(size))

        resident = self._remove_resident(key)
        if resident is not None:
            if size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            self._drop_ghost(key)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            return evicted

        if size > self.capacity:
            return []

        if key in self.ghost_probation:
            ghost_kind = 1
        elif key in self.ghost_protected:
            ghost_kind = 2
        else:
            ghost_kind = 0

        if ghost_kind:
            self._adjust_target(ghost_kind)
            self._drop_ghost(key)

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
