from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        self.capacity = max(0, int(capacity_bytes))
        self.probationary = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probationary = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.probationary_bytes = 0
        self.protected_bytes = 0
        self.used = 0
        self.protected_target = self.capacity // 2
        self.ghost_bytes = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096
        self.serial = 0

    def _drop_ghost(self, key):
        for ghosts in (self.ghost_probationary, self.ghost_protected):
            value = ghosts.pop(key, None)
            if value is not None:
                self.ghost_bytes -= value[0]

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_probationary) + len(self.ghost_protected) > self.ghost_count_limit):
            source = None
            oldest = None
            for ghosts in (self.ghost_probationary, self.ghost_protected):
                if ghosts:
                    key = next(iter(ghosts))
                    value = ghosts[key]
                    if oldest is None or value[1] < oldest[1]:
                        source = ghosts
                        oldest = value
            _, value = source.popitem(last=False)
            self.ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, kind):
        self._drop_ghost(key)
        self.serial += 1
        value = (max(1, int(size)), self.serial)
        if kind == 1:
            self.ghost_probationary[key] = value
        else:
            self.ghost_protected[key] = value
        self.ghost_bytes += value[0]
        self._trim_ghosts()

    def _adjust_target(self, kind):
        return

    def _remove_resident(self, key):
        value = self.probationary.pop(key, None)
        if value is not None:
            self.probationary_bytes -= value
            self.used -= value
            return value, False
        value = self.protected.pop(key, None)
        if value is not None:
            self.protected_bytes -= value
            self.used -= value
            return value, True
        return None, False

    def _trim_protected(self):
        while self.protected_bytes > self.protected_target and self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probationary[key] = size
            self.probationary_bytes += size

    def _evict_one(self):
        if self.probationary:
            key, size = self.probationary.popitem(last=False)
            self.probationary_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 1)
            return key
        if self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 2)
            return key
        return None

    def _make_room(self, incoming):
        evicted = []
        while self.used + incoming > self.capacity:
            key = self._evict_one()
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key, size, now):
        key = int(key)
        size = max(0, int(size))
        resident = key in self.probationary or key in self.protected

        if size <= 0 or size > self.capacity:
            if resident:
                self._remove_resident(key)
                return [key]
            return []

        if resident:
            self._remove_resident(key)
            self.protected_target = max(self.protected_target, size)
            self._trim_protected()
            evicted = self._make_room(size)
            if self.used + size > self.capacity:
                return evicted + [key]
            self._drop_ghost(key)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            return evicted

        ghost_kind = 1 if key in self.ghost_probationary else 2 if key in self.ghost_protected else 0
        if ghost_kind:
            self._adjust_target(ghost_kind)
            self._drop_ghost(key)

        self._trim_protected()
        evicted = self._make_room(size)
        if self.used + size > self.capacity:
            return evicted

        self.probationary[key] = size
        self.probationary_bytes += size
        self.used += size
        return evicted
