from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.used = 0
        self.protected_target = self.capacity // 2
        self.ghost_probation_bytes = 0
        self.ghost_protected_bytes = 0
        self.ghost_bytes = 0
        self.ghost_serial = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096

    def _remove_ghost(self, key):
        value = self.ghost_probation.pop(key, None)
        if value is not None:
            self.ghost_probation_bytes -= value[0]
            self.ghost_bytes -= value[0]
        value = self.ghost_protected.pop(key, None)
        if value is not None:
            self.ghost_protected_bytes -= value[0]
            self.ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, kind):
        self._remove_ghost(key)
        self.ghost_serial += 1
        value = (max(1, int(size)), self.ghost_serial)
        if kind == 1:
            self.ghost_probation[key] = value
            self.ghost_probation_bytes += value[0]
        else:
            self.ghost_protected[key] = value
            self.ghost_protected_bytes += value[0]
        self.ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_probation) + len(self.ghost_protected) > self.ghost_count_limit):
            kind = 0
            serial = None
            if self.ghost_probation:
                kind = 1
                serial = next(iter(self.ghost_probation.values()))[1]
            if self.ghost_protected:
                other = next(iter(self.ghost_protected.values()))[1]
                if serial is None or other < serial:
                    kind = 2
            ghosts = self.ghost_probation if kind == 1 else self.ghost_protected
            _, value = ghosts.popitem(last=False)
            if kind == 1:
                self.ghost_probation_bytes -= value[0]
            else:
                self.ghost_protected_bytes -= value[0]
            self.ghost_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        probation = self.ghost_probation_bytes
        protected = self.ghost_protected_bytes
        if kind == 1:
            delta = self.capacity if probation == 0 else max(1, min(self.capacity, protected // probation or 1))
            self.protected_target = max(0, self.protected_target - delta)
        else:
            delta = self.capacity if protected == 0 else max(1, min(self.capacity, probation // protected or 1))
            self.protected_target = min(self.capacity, self.protected_target + delta)

    def _rebalance(self):
        while self.protected_bytes > self.protected_target and self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size
            self.probation_bytes += size

    def _evict_one(self):
        if self.probation:
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
        return None

    def _make_room(self, incoming):
        evicted = []
        while self.used + incoming > self.capacity:
            key = self._evict_one()
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))

        if self.capacity <= 0:
            return []

        if key in self.probation:
            old_size = self.probation.pop(key)
            self.probation_bytes -= old_size
            self.used -= old_size
            if size <= 0 or size > self.capacity:
                return [key]
            self._rebalance()
            evicted = self._make_room(size)
            self._remove_ghost(key)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            self._rebalance()
            return evicted

        if key in self.protected:
            old_size = self.protected.pop(key)
            self.protected_bytes -= old_size
            self.used -= old_size
            if size <= 0 or size > self.capacity:
                return [key]
            self._rebalance()
            evicted = self._make_room(size)
            self._remove_ghost(key)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            self._rebalance()
            return evicted

        ghost_kind = 1 if key in self.ghost_probation else 2 if key in self.ghost_protected else 0
        if size <= 0 or size > self.capacity:
            return []

        if ghost_kind:
            self._adjust_target(ghost_kind)
            self._remove_ghost(key)

        self._rebalance()
        evicted = self._make_room(size)
        if ghost_kind:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.probation[key] = size
            self.probation_bytes += size
        self.used += size
        self._rebalance()
        return evicted
