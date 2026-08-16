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
        self.protected_target = self.capacity // 2
        self._ghost_bytes = 0
        self._ghost_serial = 0
        self._ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self._ghost_count_limit = 4096

    def _remove_ghost(self, key):
        value = self.ghost_probationary.pop(key, None)
        if value is not None:
            self.ghost_probationary_bytes -= value[0]
            self._ghost_bytes -= value[0]
            return 1
        value = self.ghost_protected.pop(key, None)
        if value is not None:
            self.ghost_protected_bytes -= value[0]
            self._ghost_bytes -= value[0]
            return 2
        return 0

    def _remember_ghost(self, key, size, kind):
        self._remove_ghost(key)
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
            candidate_kind = 0
            candidate_key = None
            candidate_serial = None
            if self.ghost_probationary:
                key, value = next(iter(self.ghost_probationary.items()))
                candidate_kind = 1
                candidate_key = key
                candidate_serial = value[1]
            if self.ghost_protected:
                key, value = next(iter(self.ghost_protected.items()))
                if candidate_serial is None or value[1] < candidate_serial:
                    candidate_kind = 2
                    candidate_key = key
            if candidate_kind == 0:
                break
            self._remove_ghost(candidate_key)

    def _adjust_target(self, ghost_kind):
        if self.capacity <= 0:
            return
        if ghost_kind == 1:
            first = self.ghost_probationary_bytes
            second = self.ghost_protected_bytes
            delta = self.capacity if first == 0 else max(1, min(self.capacity, second // first or 1))
            self.protected_target = min(self.capacity, self.protected_target + delta)
        elif ghost_kind == 2:
            first = self.ghost_probationary_bytes
            second = self.ghost_protected_bytes
            delta = self.capacity if second == 0 else max(1, min(self.capacity, first // second or 1))
            self.protected_target = max(0, self.protected_target - delta)

    def _remove_resident(self, key):
        value = self.probationary.pop(key, None)
        if value is not None:
            self.probationary_bytes -= value
            self.used -= value
            return value, 1
        value = self.protected.pop(key, None)
        if value is not None:
            self.protected_bytes -= value
            self.used -= value
            return value, 2
        return 0, 0

    def _evict_one(self, prefer_probationary):
        if prefer_probationary and self.probationary:
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

    def _make_room(self, incoming, ghost_kind=0):
        evicted = []
        while self.used + incoming > self.capacity:
            prefer_probationary = self.probationary_bytes > self.protected_target
            if ghost_kind == 1 and self.probationary_bytes >= self.protected_target:
                prefer_probationary = True
            if ghost_kind == 2 and self.probationary_bytes > self.protected_target:
                prefer_probationary = True
            key = self._evict_one(prefer_probationary)
            if key is None:
                break
            evicted.append(int(key))
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))

        if key in self.probationary:
            old_size, _ = self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size)
            self._remove_ghost(key)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            return evicted

        if key in self.protected:
            self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size)
            self._remove_ghost(key)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            return evicted

        ghost_kind = 0
        if key in self.ghost_probationary:
            ghost_kind = 1
        elif key in self.ghost_protected:
            ghost_kind = 2

        if size <= 0 or size > self.capacity:
            return []

        if ghost_kind:
            self._adjust_target(ghost_kind)
            self._remove_ghost(key)

        evicted = self._make_room(size, ghost_kind)
        if ghost_kind:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.probationary[key] = size
            self.probationary_bytes += size
        self.used += size
        return evicted
