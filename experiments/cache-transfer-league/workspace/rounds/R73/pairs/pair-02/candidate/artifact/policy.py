from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.used = 0
        self.protected_bytes = 0
        self.protected_target = self.capacity // 2
        self.ghost_serial = 0
        self.ghost_limit = 4096

    def _drop_ghost(self, key):
        self.ghost_probation.pop(key, None)
        self.ghost_protected.pop(key, None)

    def _remember_ghost(self, key, size, kind):
        self._drop_ghost(key)
        self.ghost_serial += 1
        value = (max(0, int(size)), self.ghost_serial)
        if kind == 1:
            self.ghost_probation[key] = value
        else:
            self.ghost_protected[key] = value
        while len(self.ghost_probation) + len(self.ghost_protected) > self.ghost_limit:
            oldest_kind = None
            oldest_serial = None
            if self.ghost_probation:
                oldest_kind = 1
                oldest_serial = next(iter(self.ghost_probation.values()))[1]
            if self.ghost_protected:
                serial = next(iter(self.ghost_protected.values()))[1]
                if oldest_serial is None or serial < oldest_serial:
                    oldest_kind = 2
            if oldest_kind == 1:
                self.ghost_probation.popitem(last=False)
            else:
                self.ghost_protected.popitem(last=False)

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        ghosts = self.ghost_probation if kind == 1 else self.ghost_protected
        value = ghosts.get(next(reversed(ghosts))) if ghosts else (1, 0)
        delta = max(1, min(self.capacity, value[0]))
        if kind == 1:
            self.protected_target = min(self.capacity, self.protected_target + delta)
        else:
            self.protected_target = max(0, self.protected_target - delta)

    def _rebalance(self):
        while self.protected_bytes > self.protected_target and self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size

    def _evict_one(self):
        if self.probation:
            key, size = self.probation.popitem(last=False)
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

        resident_kind = 0
        if key in self.probation:
            resident_kind = 1
            old_size = self.probation.pop(key)
            self.used -= old_size
        elif key in self.protected:
            resident_kind = 2
            old_size = self.protected.pop(key)
            self.protected_bytes -= old_size
            self.used -= old_size

        if resident_kind:
            if size > self.capacity:
                return [key]
            evicted = self._make_room(size)
            self._drop_ghost(key)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            self._rebalance()
            return evicted

        ghost_kind = 0
        if key in self.ghost_probation:
            ghost_kind = 1
        elif key in self.ghost_protected:
            ghost_kind = 2

        if size > self.capacity:
            return []

        if ghost_kind:
            self._adjust_target(ghost_kind)
            self._drop_ghost(key)

        evicted = self._make_room(size)
        if ghost_kind:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.probation[key] = size
        self.used += size
        self._rebalance()
        return evicted
