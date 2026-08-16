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
        self.ghost_probation_bytes = 0
        self.ghost_protected_bytes = 0
        self.used = 0
        self.protected_target = self.capacity // 2
        self._ghost_serial = 0
        self._ghost_bytes = 0
        self._ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self._ghost_count_limit = 4096

    def _drop_ghost(self, key):
        value = self.ghost_probation.pop(key, None)
        if value is not None:
            self.ghost_probation_bytes -= value[0]
            self._ghost_bytes -= value[0]
        value = self.ghost_protected.pop(key, None)
        if value is not None:
            self.ghost_protected_bytes -= value[0]
            self._ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, protected):
        self._drop_ghost(key)
        self._ghost_serial += 1
        value = (max(1, int(size)), self._ghost_serial)
        if protected:
            self.ghost_protected[key] = value
            self.ghost_protected_bytes += value[0]
        else:
            self.ghost_probation[key] = value
            self.ghost_probation_bytes += value[0]
        self._ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self._ghost_bytes > self._ghost_limit or
               len(self.ghost_probation) + len(self.ghost_protected) > self._ghost_count_limit):
            source = None
            if self.ghost_probation:
                source = self.ghost_probation
            if self.ghost_protected:
                if source is None:
                    source = self.ghost_protected
                elif next(iter(self.ghost_protected.values()))[1] < next(iter(source.values()))[1]:
                    source = self.ghost_protected
            _, value = source.popitem(last=False)
            if source is self.ghost_probation:
                self.ghost_probation_bytes -= value[0]
            else:
                self.ghost_protected_bytes -= value[0]
            self._ghost_bytes -= value[0]

    def _adjust_target(self, protected_hit):
        if self.capacity <= 0:
            return
        if protected_hit:
            denominator = self.ghost_protected_bytes
            delta = (self.capacity if denominator == 0 else
                     max(1, min(self.capacity, self.ghost_probation_bytes // denominator or 1)))
            self.protected_target = min(self.capacity, self.protected_target + delta)
        else:
            denominator = self.ghost_probation_bytes
            delta = (self.capacity if denominator == 0 else
                     max(1, min(self.capacity, self.ghost_protected_bytes // denominator or 1)))
            self.protected_target = max(0, self.protected_target - delta)

    def _rebalance(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size
            self.probation_bytes += size

    def _make_room(self, incoming):
        evicted = []
        while self.used + incoming > self.capacity:
            if self.probation:
                key, size = self.probation.popitem(last=False)
                self.probation_bytes -= size
                self.used -= size
                self._remember_ghost(key, size, False)
            elif self.protected:
                key, size = self.protected.popitem(last=False)
                self.protected_bytes -= size
                self.used -= size
                self._remember_ghost(key, size, True)
            else:
                break
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))

        if key in self.probation:
            old_size = self.probation.pop(key)
            self.probation_bytes -= old_size
            self.used -= old_size
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            self._drop_ghost(key)
            self._rebalance()
            return evicted

        if key in self.protected:
            old_size = self.protected.pop(key)
            self.protected_bytes -= old_size
            self.used -= old_size
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            self._drop_ghost(key)
            self._rebalance()
            return evicted

        ghost_kind = 0
        if key in self.ghost_probation:
            ghost_kind = 1
        elif key in self.ghost_protected:
            ghost_kind = 2

        if size <= 0 or size > self.capacity:
            return []

        if ghost_kind:
            self._adjust_target(ghost_kind == 2)
            self._drop_ghost(key)

        evicted = self._make_room(size)
        if ghost_kind:
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            self._rebalance()
        else:
            self.probation[key] = size
            self.probation_bytes += size
            self.used += size
        return evicted
