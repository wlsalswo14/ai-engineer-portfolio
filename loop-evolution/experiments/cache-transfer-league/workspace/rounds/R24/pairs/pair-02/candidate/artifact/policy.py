from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0
        self.ghost_recent_bytes = 0
        self.ghost_protected_bytes = 0
        self._tick = 0
        self._protected_floor = max(1, self.capacity_bytes // 4) if self.capacity_bytes else 0
        self._protected_target = max(1, self.capacity_bytes // 2) if self.capacity_bytes else 0

    def _step(self, size):
        return max(1, min(max(1, self.capacity_bytes // 8), max(1, int(size))))

    def _raise_target(self, size):
        if self.capacity_bytes:
            self._protected_target = min(self.capacity_bytes, self._protected_target + self._step(size))

    def _lower_target(self, size):
        if self.capacity_bytes:
            self._protected_target = max(self._protected_floor, self._protected_target - self._step(size))

    def _forget_ghost(self, key):
        size = self.ghost_recent.pop(key, None)
        if size is not None:
            self.ghost_recent_bytes -= size
        size = self.ghost_protected.pop(key, None)
        if size is not None:
            self.ghost_protected_bytes -= size

    def _trim_ghosts(self):
        limit = self.capacity_bytes * 2
        while self.ghost_recent_bytes + self.ghost_protected_bytes > limit:
            if self.ghost_recent:
                _, size = self.ghost_recent.popitem(last=False)
                self.ghost_recent_bytes -= size
            elif self.ghost_protected:
                _, size = self.ghost_protected.popitem(last=False)
                self.ghost_protected_bytes -= size
            else:
                break

    def _remember_ghost(self, key, size, was_protected):
        self._forget_ghost(key)
        if was_protected:
            self.ghost_protected[key] = size
            self.ghost_protected_bytes += size
        else:
            self.ghost_recent[key] = size
            self.ghost_recent_bytes += size
        self._trim_ghosts()

    def _rebalance(self):
        while self.protected and len(self.protected) > 1 and self.protected_bytes > self._protected_target:
            key, entry = self.protected.popitem(last=False)
            self.protected_bytes -= entry[0]
            self.probation[key] = entry

    def _evict_one(self):
        if self.probation:
            key, entry = self.probation.popitem(last=False)
            self.used_bytes -= entry[0]
            self._remember_ghost(key, entry[0], False)
            return key
        if self.protected:
            key, entry = self.protected.popitem(last=False)
            self.used_bytes -= entry[0]
            self.protected_bytes -= entry[0]
            self._remember_ghost(key, entry[0], True)
            return key
        return None

    def access(self, key: int, size: int, now: int) -> list[int]:
        self._tick += 1

        if key in self.protected:
            entry = self.protected.pop(key)
            entry[1] += 1
            entry[2] = self._tick
            self.protected[key] = entry
            return []

        if key in self.probation:
            entry = self.probation.pop(key)
            entry[1] += 1
            entry[2] = self._tick
            self.protected[key] = entry
            self.protected_bytes += entry[0]
            self._raise_target(entry[0])
            self._rebalance()
            return []

        recent_hit = key in self.ghost_recent
        protected_hit = key in self.ghost_protected
        self._forget_ghost(key)

        if self.capacity_bytes == 0 or size <= 0 or size > self.capacity_bytes:
            return []

        if recent_hit:
            self._raise_target(size)
        elif protected_hit:
            self._lower_target(size)

        self._rebalance()
        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._evict_one()
            if old_key is None:
                break
            evicted.append(old_key)

        entry = [size, 2 if recent_hit or protected_hit else 1, self._tick]
        if recent_hit or protected_hit:
            self.protected[key] = entry
            self.protected_bytes += size
        else:
            self.probation[key] = entry
        self.used_bytes += size
        self._rebalance()
        return evicted
