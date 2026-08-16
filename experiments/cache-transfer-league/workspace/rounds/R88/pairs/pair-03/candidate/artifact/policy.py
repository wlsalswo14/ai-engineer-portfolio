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
        self.target = self.capacity // 2
        self.ghost_bytes = 0
        base = max(1, self.capacity)
        self.ghost_limit = max(64, min(1 << 20, 2 * base))
        self.ghost_count_limit = 4096
        self.serial = 0

    def _forget_ghost(self, key):
        for table in (self.ghost_probationary, self.ghost_protected):
            value = table.pop(key, None)
            if value is not None:
                self.ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, kind):
        self._forget_ghost(key)
        self.serial += 1
        value = (size, self.serial)
        if kind == 1:
            self.ghost_probationary[key] = value
        else:
            self.ghost_protected[key] = value
        self.ghost_bytes += size
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_probationary) + len(self.ghost_protected) > self.ghost_count_limit):
            chosen = None
            chosen_table = None
            for table in (self.ghost_probationary, self.ghost_protected):
                if table:
                    _, value = next(iter(table.items()))
                    if chosen is None or value[1] < chosen[1]:
                        chosen = value
                        chosen_table = table
            if chosen_table is None:
                break
            _, value = chosen_table.popitem(last=False)
            self.ghost_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        b1 = sum(value[0] for value in self.ghost_probationary.values())
        b2 = sum(value[0] for value in self.ghost_protected.values())
        if kind == 1:
            delta = self.capacity if b1 == 0 else max(1, min(self.capacity, b2 // b1 or 1))
            self.target = min(self.capacity, self.target + delta)
        else:
            delta = self.capacity if b2 == 0 else max(1, min(self.capacity, b1 // b2 or 1))
            self.target = max(0, self.target - delta)

    def _rebalance(self):
        while len(self.protected) > 1 and self.protected_bytes > self.target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probationary[key] = size
            self.probationary_bytes += size

    def _remove_resident(self, key):
        value = self.probationary.pop(key, None)
        if value is not None:
            self.probationary_bytes -= value
            self.used -= value
            return value
        value = self.protected.pop(key, None)
        if value is not None:
            self.protected_bytes -= value
            self.used -= value
            return value
        return None

    def _evict_probationary(self):
        if not self.probationary:
            return None
        key, size = self.probationary.popitem(last=False)
        self.probationary_bytes -= size
        self.used -= size
        self._remember_ghost(key, size, 1)
        return key

    def _evict_protected(self):
        if not self.protected:
            return None
        key, size = self.protected.popitem(last=False)
        self.protected_bytes -= size
        self.used -= size
        self._remember_ghost(key, size, 2)
        return key

    def _make_room(self, incoming):
        evicted = []
        while self.used + incoming > self.capacity:
            key = self._evict_probationary()
            if key is None:
                key = self._evict_protected()
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key, size, now):
        key = int(key)
        size = max(0, int(size))

        if key in self.probationary:
            old_size = self.probationary.pop(key)
            self.probationary_bytes -= old_size
            self.used -= old_size
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size)
            if self.used + size > self.capacity:
                return evicted + [key]
            self._forget_ghost(key)
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
            evicted = self._make_room(size)
            if self.used + size > self.capacity:
                return evicted + [key]
            self._forget_ghost(key)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            self._rebalance()
            return evicted

        kind = 0
        if key in self.ghost_probationary:
            kind = 1
        elif key in self.ghost_protected:
            kind = 2
        if size <= 0 or size > self.capacity:
            return []

        if kind:
            self._adjust_target(kind)
            self._forget_ghost(key)
            self._rebalance()

        evicted = self._make_room(size)
        if self.used + size > self.capacity:
            return evicted

        if kind:
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            self._rebalance()
        else:
            self.probationary[key] = size
            self.probationary_bytes += size
            self.used += size
        return evicted
