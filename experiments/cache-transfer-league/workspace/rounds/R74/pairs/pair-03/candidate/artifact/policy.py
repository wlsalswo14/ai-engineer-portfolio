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
        self.probation_target = self.capacity // 2
        self.ghost_bytes = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096
        self.serial = 0

    def _forget_ghost(self, key):
        value = self.ghost_probation.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[1]
        value = self.ghost_protected.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[1]

    def _remember_ghost(self, key, size, protected):
        self._forget_ghost(key)
        self.serial += 1
        value = (self.serial, max(1, int(size)))
        target = self.ghost_protected if protected else self.ghost_probation
        target[key] = value
        self.ghost_bytes += value[1]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_probation) + len(self.ghost_protected) > self.ghost_count_limit):
            oldest_kind = None
            oldest_serial = None
            if self.ghost_probation:
                oldest_kind = self.ghost_probation
                oldest_serial = next(iter(self.ghost_probation.values()))[0]
            if self.ghost_protected:
                serial = next(iter(self.ghost_protected.values()))[0]
                if oldest_serial is None or serial < oldest_serial:
                    oldest_kind = self.ghost_protected
            if oldest_kind is None:
                break
            _, value = oldest_kind.popitem(last=False)
            self.ghost_bytes -= value[1]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        if kind == 1:
            other = sum(value[1] for value in self.ghost_protected.values())
            own = sum(value[1] for value in self.ghost_probation.values())
            delta = self.capacity if own == 0 else max(1, min(self.capacity, other // own or 1))
            self.probation_target = min(self.capacity, self.probation_target + delta)
        else:
            other = sum(value[1] for value in self.ghost_probation.values())
            own = sum(value[1] for value in self.ghost_protected.values())
            delta = self.capacity if own == 0 else max(1, min(self.capacity, other // own or 1))
            self.probation_target = max(0, self.probation_target - delta)

    def _remove_resident(self, key):
        value = self.probation.pop(key, None)
        if value is not None:
            self.probation_bytes -= value
            self.used -= value
            return value, False
        value = self.protected.pop(key, None)
        if value is not None:
            self.protected_bytes -= value
            self.used -= value
            return value, True
        return 0, False

    def _evict_one(self):
        use_probation = bool(self.probation) and (
            not self.protected or self.probation_bytes > self.probation_target
        )
        if use_probation:
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

        if key in self.probation or key in self.protected:
            old_size, was_protected = self._remove_resident(key)
            if size == 0 or size > self.capacity:
                self._remember_ghost(key, old_size, was_protected)
                return [key]
            evicted = self._make_room(size)
            if was_protected:
                self.protected[key] = size
                self.protected_bytes += size
            else:
                self.protected[key] = size
                self.protected_bytes += size
            self.used += size
            return evicted

        ghost_kind = 1 if key in self.ghost_probation else 2 if key in self.ghost_protected else 0
        if size == 0 or size > self.capacity:
            return []

        if ghost_kind:
            self._adjust_target(ghost_kind)
            self._forget_ghost(key)
            evicted = self._make_room(size)
            self.protected[key] = size
            self.protected_bytes += size
        else:
            evicted = self._make_room(size)
            self.probation[key] = size
            self.probation_bytes += size
        self.used += size
        return evicted
