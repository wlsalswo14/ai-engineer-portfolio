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
        self.ghost_probation_bytes = 0
        self.ghost_protected_bytes = 0
        self.ghost_bytes = 0
        self.used = 0
        self.target = self.capacity // 2
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096
        self.serial = 0

    def _drop_ghost(self, key):
        value = self.ghost_probation.pop(key, None)
        if value is not None:
            self.ghost_probation_bytes -= value[0]
            self.ghost_bytes -= value[0]
        value = self.ghost_protected.pop(key, None)
        if value is not None:
            self.ghost_protected_bytes -= value[0]
            self.ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, protected):
        self._drop_ghost(key)
        self.serial += 1
        value = (max(1, int(size)), self.serial)
        ghosts = self.ghost_protected if protected else self.ghost_probation
        ghosts[key] = value
        if protected:
            self.ghost_protected_bytes += value[0]
        else:
            self.ghost_probation_bytes += value[0]
        self.ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_probation) + len(self.ghost_protected) > self.ghost_count_limit):
            chosen = None
            chosen_map = None
            for ghosts in (self.ghost_probation, self.ghost_protected):
                if ghosts:
                    key, value = next(iter(ghosts.items()))
                    if chosen is None or value[1] < chosen[1]:
                        chosen = (key, value)
                        chosen_map = ghosts
            key, value = chosen_map.popitem(last=False)
            self.ghost_bytes -= value[0]
            if chosen_map is self.ghost_probation:
                self.ghost_probation_bytes -= value[0]
            else:
                self.ghost_protected_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        probation = self.ghost_probation_bytes
        protected = self.ghost_protected_bytes
        if kind == 1:
            delta = self.capacity if probation == 0 else max(1, min(self.capacity, protected // probation or 1))
            self.target = min(self.capacity, self.target + delta)
        else:
            delta = self.capacity if protected == 0 else max(1, min(self.capacity, probation // protected or 1))
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
            prefer_probation = self.probation_bytes > self.target
            if ghost_kind == 1 and self.probation_bytes >= self.target:
                prefer_probation = True
            elif ghost_kind == 2 and self.probation_bytes == self.target:
                prefer_probation = False
            key = self._evict_one(prefer_probation)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def _rebalance_protected(self):
        limit = max(0, self.capacity - self.target)
        while self.protected and self.protected_bytes > limit:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size
            self.probation_bytes += size

    def access(self, key, size, now):
        key = int(key)
        size = max(0, int(size))
        old_size = self._remove_resident(key)

        if old_size is not None:
            if size <= 0:
                size = old_size
            if size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            if self.used + size > self.capacity:
                return evicted + [key]
            self._drop_ghost(key)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            self._rebalance_protected()
            return evicted

        if size <= 0 or size > self.capacity:
            return []

        ghost_kind = 1 if key in self.ghost_probation else 2 if key in self.ghost_protected else 0
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
        self._rebalance_protected()
        return evicted
