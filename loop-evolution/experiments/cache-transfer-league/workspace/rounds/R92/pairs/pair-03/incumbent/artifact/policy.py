from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        self.capacity = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.used = 0
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.target = self.capacity // 2
        self.serial = 0
        self.ghost_bytes = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096

    def _forget_ghost(self, key):
        value = self.ghost_probation.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]
        value = self.ghost_protected.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, segment):
        self._forget_ghost(key)
        self.serial += 1
        value = (size, self.serial)
        if segment == 1:
            self.ghost_probation[key] = value
        else:
            self.ghost_protected[key] = value
        self.ghost_bytes += size
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

    def _adapt(self, segment):
        if self.capacity <= 0:
            return
        probation_ghost_bytes = sum(value[0] for value in self.ghost_probation.values())
        protected_ghost_bytes = sum(value[0] for value in self.ghost_protected.values())
        if segment == 1:
            step = self.capacity if probation_ghost_bytes == 0 else max(1, protected_ghost_bytes // probation_ghost_bytes)
            self.target = min(self.capacity, self.target + min(self.capacity, step))
        else:
            step = self.capacity if protected_ghost_bytes == 0 else max(1, probation_ghost_bytes // protected_ghost_bytes)
            self.target = max(0, self.target - min(self.capacity, step))

    def _remove(self, key):
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
        return None, 0

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

    def _room(self, incoming, ghost_segment):
        evicted = []
        while self.used + incoming > self.capacity:
            prefer_probation = self.probation_bytes > self.target
            if ghost_segment == 1 and self.probation_bytes >= self.target:
                prefer_probation = True
            elif ghost_segment == 2 and self.probation_bytes <= self.target:
                prefer_probation = False
            key = self._evict_one(prefer_probation)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def _rebalance(self):
        protected_limit = max(0, self.capacity - self.target)
        while self.protected_bytes > protected_limit and self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size
            self.probation_bytes += size

    def access(self, key, size, now):
        key = int(key)
        size = max(0, int(size))
        if self.capacity <= 0 or size <= 0 or size > self.capacity:
            return []

        if key in self.probation or key in self.protected:
            old_size, segment = self._remove(key)
            if old_size == size:
                self.protected[key] = size
                self.protected_bytes += size
                self.used += size
                self._rebalance()
                return []
            evicted = self._room(size, 0)
            if self.used + size > self.capacity:
                self._remember_ghost(key, old_size, segment)
                return evicted
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            self._rebalance()
            return evicted

        ghost_segment = 1 if key in self.ghost_probation else 2 if key in self.ghost_protected else 0
        if ghost_segment:
            self._adapt(ghost_segment)
            self._forget_ghost(key)

        evicted = self._room(size, ghost_segment)
        if self.used + size > self.capacity:
            return evicted

        if ghost_segment:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.probation[key] = size
            self.probation_bytes += size
        self.used += size
        self._rebalance()
        return evicted
