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
        self.clock = 0
        self.ghost_bytes = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096

    def _remove_ghost(self, key):
        value = self.ghost_probationary.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]
        value = self.ghost_protected.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, protected):
        self._remove_ghost(key)
        self.clock += 1
        value = (max(1, int(size)), self.clock)
        target = self.ghost_protected if protected else self.ghost_probationary
        target[key] = value
        self.ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_probationary) + len(self.ghost_protected) > self.ghost_count_limit):
            source = None
            oldest = None
            for candidate in (self.ghost_probationary, self.ghost_protected):
                if candidate:
                    key = next(iter(candidate))
                    value = candidate[key]
                    if oldest is None or value[1] < oldest[1]:
                        source = candidate
                        oldest = value
            _, value = source.popitem(last=False)
            self.ghost_bytes -= value[0]

    def _adapt(self, protected_ghost):
        if self.capacity <= 0:
            return
        probationary_bytes = sum(value[0] for value in self.ghost_probationary.values())
        protected_bytes = sum(value[0] for value in self.ghost_protected.values())
        if protected_ghost:
            delta = self.capacity if probationary_bytes == 0 else max(1, min(self.capacity, protected_bytes // probationary_bytes or 1))
            self.protected_target = min(self.capacity, self.protected_target + delta)
        else:
            delta = self.capacity if protected_bytes == 0 else max(1, min(self.capacity, probationary_bytes // protected_bytes or 1))
            self.protected_target = max(0, self.protected_target - delta)

    def _rebalance(self):
        while self.protected_bytes > self.protected_target and self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probationary[key] = size
            self.probationary_bytes += size

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

    def _evict_one(self, prefer_probationary):
        if prefer_probationary and self.probationary:
            key, size = self.probationary.popitem(last=False)
            self.probationary_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, False)
            return key
        if self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, True)
            return key
        if self.probationary:
            key, size = self.probationary.popitem(last=False)
            self.probationary_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, False)
            return key
        return None

    def _make_room(self, incoming, ghost_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            boundary = self.capacity - self.protected_target
            prefer_probationary = self.probationary_bytes > boundary
            if ghost_kind == 1 and self.probationary_bytes >= boundary:
                prefer_probationary = True
            elif ghost_kind == 2 and self.probationary_bytes == boundary:
                prefer_probationary = False
            key = self._evict_one(prefer_probationary)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key, size, now):
        key = int(key)
        size = max(0, int(size))

        if key in self.probationary or key in self.protected:
            self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            if self.used + size > self.capacity:
                return evicted + [key]
            self._remove_ghost(key)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            self._rebalance()
            return evicted

        ghost_kind = 1 if key in self.ghost_probationary else 2 if key in self.ghost_protected else 0
        if size <= 0 or size > self.capacity:
            return []
        if ghost_kind:
            self._adapt(ghost_kind == 2)
            self._remove_ghost(key)

        evicted = self._make_room(size, ghost_kind)
        if self.used + size > self.capacity:
            return evicted
        if ghost_kind:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.probationary[key] = size
            self.probationary_bytes += size
        self.used += size
        self._rebalance()
        return evicted
