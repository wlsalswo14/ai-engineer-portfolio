from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.probationary = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probationary = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.probationary_bytes = 0
        self.protected_bytes = 0
        self.ghost_probationary_bytes = 0
        self.ghost_protected_bytes = 0
        self.used = 0
        self.probationary_target = self.capacity // 2
        self._ghost_serial = 0
        self._ghost_bytes = 0
        self._ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self._ghost_count_limit = 4096

    def _drop_ghost(self, key):
        value = self.ghost_probationary.pop(key, None)
        if value is not None:
            self.ghost_probationary_bytes -= value[0]
            self._ghost_bytes -= value[0]
        value = self.ghost_protected.pop(key, None)
        if value is not None:
            self.ghost_protected_bytes -= value[0]
            self._ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, kind):
        self._drop_ghost(key)
        self._ghost_serial += 1
        value = (max(1, int(size)), self._ghost_serial)
        if kind == 1:
            self.ghost_probationary[key] = value
            self.ghost_probationary_bytes += value[0]
        else:
            self.ghost_protected[key] = value
            self.ghost_protected_bytes += value[0]
        self._ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self._ghost_bytes > self._ghost_limit or
               len(self.ghost_probationary) + len(self.ghost_protected) > self._ghost_count_limit):
            kind = 0
            serial = None
            if self.ghost_probationary:
                kind = 1
                serial = next(iter(self.ghost_probationary.values()))[1]
            if self.ghost_protected:
                other = next(iter(self.ghost_protected.values()))[1]
                if serial is None or other < serial:
                    kind = 2
            ghosts = self.ghost_probationary if kind == 1 else self.ghost_protected
            _, value = ghosts.popitem(last=False)
            if kind == 1:
                self.ghost_probationary_bytes -= value[0]
            else:
                self.ghost_protected_bytes -= value[0]
            self._ghost_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        b1 = self.ghost_probationary_bytes
        b2 = self.ghost_protected_bytes
        if kind == 1:
            delta = self.capacity if b1 == 0 else max(1, min(self.capacity, b2 // b1 or 1))
            self.probationary_target = min(self.capacity, self.probationary_target + delta)
        else:
            delta = self.capacity if b2 == 0 else max(1, min(self.capacity, b1 // b2 or 1))
            self.probationary_target = max(0, self.probationary_target - delta)

    def _evict_probationary(self):
        if not self.probationary:
            return None
        key, size = self.probationary.popitem(last=False)
        self.probationary_bytes -= size
        self.used -= size
        self._remember_ghost(key, size, 1)
        return key

    def _evict_protected(self):
        if not self.protected:
            return None
        key, size = self.protected.popitem(last=False)
        self.protected_bytes -= size
        self.used -= size
        self._remember_ghost(key, size, 2)
        return key

    def _make_room(self, incoming, incoming_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            key = None
            if incoming_kind == 2 and self.probationary:
                key = self._evict_probationary()
            elif (incoming_kind == 1 and self.protected and
                  self.protected_bytes > self.probationary_target):
                key = self._evict_protected()
            elif self.probationary:
                key = self._evict_probationary()
            elif self.protected:
                key = self._evict_protected()
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        if type(key) is not int:
            return []
        size = max(0, int(size))

        if key in self.probationary:
            old_size = self.probationary.pop(key)
            self.probationary_bytes -= old_size
            self.used -= old_size
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 2)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            return evicted

        if key in self.protected:
            old_size = self.protected.pop(key)
            self.protected_bytes -= old_size
            self.used -= old_size
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 2)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            return evicted

        ghost_kind = 1 if key in self.ghost_probationary else 2 if key in self.ghost_protected else 0
        if size <= 0 or size > self.capacity:
            return []

        if ghost_kind:
            self._adjust_target(ghost_kind)
            self._drop_ghost(key)

        resident_kind = 2 if ghost_kind == 2 else 1
        evicted = self._make_room(size, resident_kind)
        if resident_kind == 2:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.probationary[key] = size
            self.probationary_bytes += size
        self.used += size
        return evicted
