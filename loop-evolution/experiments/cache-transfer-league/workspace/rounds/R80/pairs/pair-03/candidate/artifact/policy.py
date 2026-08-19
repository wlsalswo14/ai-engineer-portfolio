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
        self.target = self.capacity // 2
        self._clock = 0
        self._ghost_bytes = 0
        self._ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self._ghost_count_limit = 4096

    def _remove_ghost(self, key):
        value = self.ghost_probationary.pop(key, None)
        if value is not None:
            self._ghost_bytes -= value[0]
        value = self.ghost_protected.pop(key, None)
        if value is not None:
            self._ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, protected):
        if self.capacity <= 0:
            return
        self._remove_ghost(key)
        self._clock += 1
        value = (max(1, int(size)), self._clock)
        if protected:
            self.ghost_protected[key] = value
        else:
            self.ghost_probationary[key] = value
        self._ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self._ghost_bytes > self._ghost_limit or
               len(self.ghost_probationary) + len(self.ghost_protected) > self._ghost_count_limit):
            candidate = None
            source = None
            if self.ghost_probationary:
                candidate = next(iter(self.ghost_probationary))
                source = self.ghost_probationary
            if self.ghost_protected:
                other = next(iter(self.ghost_protected))
                if candidate is None or self.ghost_protected[other][1] < source[candidate][1]:
                    candidate = other
                    source = self.ghost_protected
            value = source.pop(candidate)
            self._ghost_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        if kind == 1:
            first = sum(value[0] for value in self.ghost_probationary.values())
            second = sum(value[0] for value in self.ghost_protected.values())
            delta = self.capacity if first == 0 else max(1, min(self.capacity, second // first or 1))
            self.target = min(self.capacity, self.target + delta)
        else:
            first = sum(value[0] for value in self.ghost_probationary.values())
            second = sum(value[0] for value in self.ghost_protected.values())
            delta = self.capacity if second == 0 else max(1, min(self.capacity, first // second or 1))
            self.target = max(0, self.target - delta)

    def _evict_one(self):
        if self.probationary and (self.probationary_bytes > self.target or not self.protected):
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

        entry = self.probationary.pop(key, None)
        if entry is not None:
            old_size = entry
            self.probationary_bytes -= old_size
            self.used -= old_size
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size)
            self._remove_ghost(key)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            return evicted

        entry = self.protected.pop(key, None)
        if entry is not None:
            old_size = entry
            self.protected_bytes -= old_size
            self.used -= old_size
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size)
            self._remove_ghost(key)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            return evicted

        if size <= 0 or size > self.capacity:
            return []

        kind = 1 if key in self.ghost_probationary else 2 if key in self.ghost_protected else 0
        if kind:
            self._adjust_target(kind)
            self._remove_ghost(key)

        evicted = self._make_room(size)
        if kind:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.probationary[key] = size
            self.probationary_bytes += size
        self.used += size
        return evicted
