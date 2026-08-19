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
        self.used = 0
        self.protected_target = self.capacity // 2
        self.ghost_bytes = 0
        self.ghost_serial = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096

    def _forget_ghost(self, key):
        value = self.ghost_probationary.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]
        value = self.ghost_protected.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, protected):
        self._forget_ghost(key)
        self.ghost_serial += 1
        value = (max(1, int(size)), self.ghost_serial)
        if protected:
            self.ghost_protected[key] = value
        else:
            self.ghost_probationary[key] = value
        self.ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_probationary) + len(self.ghost_protected) > self.ghost_count_limit):
            oldest_kind = None
            oldest_serial = None
            if self.ghost_probationary:
                oldest_kind = 0
                oldest_serial = next(iter(self.ghost_probationary.values()))[1]
            if self.ghost_protected:
                serial = next(iter(self.ghost_protected.values()))[1]
                if oldest_serial is None or serial < oldest_serial:
                    oldest_kind = 1
            ghosts = self.ghost_protected if oldest_kind else self.ghost_probationary
            _, value = ghosts.popitem(last=False)
            self.ghost_bytes -= value[0]

    def _adapt(self, kind):
        if self.capacity <= 0:
            return
        if kind == 1:
            left = self.ghost_probationary_bytes()
            right = self.ghost_protected_bytes()
            delta = self.capacity if left == 0 else max(1, min(self.capacity, right // left or 1))
            self.protected_target = max(0, self.protected_target - delta)
        else:
            left = self.ghost_protected_bytes()
            right = self.ghost_probationary_bytes()
            delta = self.capacity if left == 0 else max(1, min(self.capacity, right // left or 1))
            self.protected_target = min(self.capacity, self.protected_target + delta)

    def ghost_probationary_bytes(self):
        return sum(value[0] for value in self.ghost_probationary.values())

    def ghost_protected_bytes(self):
        return sum(value[0] for value in self.ghost_protected.values())

    def _remove_resident(self, key):
        value = self.probationary.pop(key, None)
        if value is not None:
            self.probationary_bytes -= value
            self.used -= value
            return value, 0
        value = self.protected.pop(key, None)
        if value is not None:
            self.protected_bytes -= value
            self.used -= value
            return value, 1
        return 0, -1

    def _evict_one(self, ghost_kind):
        recency_target = self.capacity - self.protected_target
        if ghost_kind == 1 and self.probationary:
            key, size = self.probationary.popitem(last=False)
            segment = 0
        elif self.probationary and (self.probationary_bytes > recency_target or not self.protected):
            key, size = self.probationary.popitem(last=False)
            segment = 0
        elif self.protected:
            key, size = self.protected.popitem(last=False)
            segment = 1
        elif self.probationary:
            key, size = self.probationary.popitem(last=False)
            segment = 0
        else:
            return None
        if segment:
            self.protected_bytes -= size
        else:
            self.probationary_bytes -= size
        self.used -= size
        self._remember_ghost(key, size, segment == 1)
        return key

    def _make_room(self, incoming, ghost_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            key = self._evict_one(ghost_kind)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))

        if key in self.probationary:
            self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            return evicted

        if key in self.protected:
            self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            return evicted

        ghost_kind = 1 if key in self.ghost_probationary else 2 if key in self.ghost_protected else 0
        if size <= 0 or size > self.capacity:
            self._forget_ghost(key)
            return []

        if ghost_kind:
            self._adapt(ghost_kind)
            self._forget_ghost(key)

        evicted = self._make_room(size, ghost_kind)
        if ghost_kind == 2:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.probationary[key] = size
            self.probationary_bytes += size
        self.used += size
        return evicted
