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
        self._ghost_serial = 0
        self._ghost_bytes = 0
        self._ghost_byte_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self._ghost_count_limit = 4096

    def _drop_ghost(self, key):
        for ghosts in (self.ghost_probationary, self.ghost_protected):
            value = ghosts.pop(key, None)
            if value is not None:
                self._ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, kind):
        self._drop_ghost(key)
        self._ghost_serial += 1
        value = (max(0, int(size)), self._ghost_serial)
        ghosts = self.ghost_probationary if kind == 1 else self.ghost_protected
        ghosts[key] = value
        self._ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self._ghost_bytes > self._ghost_byte_limit or
               len(self.ghost_probationary) + len(self.ghost_protected) > self._ghost_count_limit):
            selected = None
            selected_serial = None
            for kind, ghosts in ((1, self.ghost_probationary), (2, self.ghost_protected)):
                if ghosts:
                    serial = next(iter(ghosts.values()))[1]
                    if selected_serial is None or serial < selected_serial:
                        selected = ghosts
                        selected_serial = serial
            if selected is None:
                break
            _, value = selected.popitem(last=False)
            self._ghost_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        b1 = sum(value[0] for value in self.ghost_probationary.values())
        b2 = sum(value[0] for value in self.ghost_protected.values())
        if kind == 1:
            delta = self.capacity if b1 == 0 else max(1, min(self.capacity, b2 // b1 or 1))
            self.protected_target = min(self.capacity, self.protected_target + delta)
        else:
            delta = self.capacity if b2 == 0 else max(1, min(self.capacity, b1 // b2 or 1))
            self.protected_target = max(0, self.protected_target - delta)

    def _remove_resident(self, key):
        if key in self.probationary:
            size = self.probationary.pop(key)
            self.probationary_bytes -= size
            self.used -= size
            return size, 1
        if key in self.protected:
            size = self.protected.pop(key)
            self.protected_bytes -= size
            self.used -= size
            return size, 2
        return 0, 0

    def _rebalance_protected(self):
        limit = self.capacity - self.protected_target
        while self.protected and self.protected_bytes > limit:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probationary[key] = size
            self.probationary_bytes += size

    def _evict_one(self):
        if self.probationary and (self.probationary_bytes > self.protected_target or not self.protected):
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
        if self.probationary:
            key, size = self.probationary.popitem(last=False)
            self.probationary_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 1)
            return key
        return None

    def _make_room(self, incoming):
        self._rebalance_protected()
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

        if key in self.probationary or key in self.protected:
            old_size, old_kind = self._remove_resident(key)
            if size > self.capacity:
                self._remember_ghost(key, old_size, old_kind)
                return [key]
            evicted = self._make_room(size)
            self._drop_ghost(key)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            self._rebalance_protected()
            return evicted

        ghost_kind = 0
        if key in self.ghost_probationary:
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
            self.probationary[key] = size
            self.probationary_bytes += size
        self.used += size
        self._rebalance_protected()
        return evicted
