class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.used = 0
        self.tick = 0
        self.probation = {}
        self.protected = {}
        self.ghost_probation = {}
        self.ghost_protected = {}
        self.protected_target = (self.capacity * 3) // 4
        self.ghost_limit = 4096

    def _oldest(self, table):
        return min(table, key=lambda k: (table[k][1], k))

    def _remember(self, key, protected):
        first = self.ghost_protected if protected else self.ghost_probation
        other = self.ghost_probation if protected else self.ghost_protected
        other.pop(key, None)
        first[key] = self.tick
        while len(self.ghost_probation) + len(self.ghost_protected) > self.ghost_limit:
            if self.ghost_probation and self.ghost_protected:
                a = min(self.ghost_probation, key=lambda k: (self.ghost_probation[k], k))
                b = min(self.ghost_protected, key=lambda k: (self.ghost_protected[k], k))
                if (self.ghost_probation[a], a) <= (self.ghost_protected[b], b):
                    del self.ghost_probation[a]
                else:
                    del self.ghost_protected[b]
            elif self.ghost_probation:
                del self.ghost_probation[min(self.ghost_probation, key=lambda k: (self.ghost_probation[k], k))]
            else:
                del self.ghost_protected[min(self.ghost_protected, key=lambda k: (self.ghost_protected[k], k))]

    def _trim_protected(self):
        while self.protected and sum(v[0] for v in self.protected.values()) > self.protected_target:
            key = self._oldest(self.protected)
            data = self.protected.pop(key)
            data[3] = 0
            self.probation[key] = data

    def _evict_one(self, evicted):
        if self.probation:
            key = self._oldest(self.probation)
            data = self.probation.pop(key)
            self._remember(key, False)
        elif self.protected:
            key = self._oldest(self.protected)
            data = self.protected.pop(key)
            self._remember(key, True)
        else:
            return
        self.used -= data[0]
        evicted.append(key)

    def _touch(self, table, key):
        data = table[key]
        data[1] = self.tick
        data[2] += 1

    def access(self, key: int, size: int, now: int) -> list[int]:
        self.tick += 1
        if key in self.probation:
            self._touch(self.probation, key)
            data = self.probation.pop(key)
            data[3] = 1
            self.protected[key] = data
            self.ghost_probation.pop(key, None)
            self.ghost_protected.pop(key, None)
            self._trim_protected()
            return []
        if key in self.protected:
            self._touch(self.protected, key)
            self.ghost_probation.pop(key, None)
            self.ghost_protected.pop(key, None)
            return []
        requested = int(size)
        if self.capacity <= 0 or requested <= 0 or requested > self.capacity:
            return []
        was_probation_ghost = key in self.ghost_probation
        was_protected_ghost = key in self.ghost_protected
        if was_probation_ghost:
            delta = max(1, min(requested, max(1, self.capacity // 8)))
            self.protected_target = min(self.capacity, self.protected_target + delta)
        elif was_protected_ghost:
            delta = max(1, min(requested, max(1, self.capacity // 8)))
            self.protected_target = max(0, self.protected_target - delta)
        self.ghost_probation.pop(key, None)
        self.ghost_protected.pop(key, None)
        data = [requested, self.tick, 1, 1 if was_probation_ghost or was_protected_ghost else 0]
        if data[3]:
            self.protected[key] = data
        else:
            self.probation[key] = data
        self.used += requested
        self._trim_protected()
        evicted = []
        while self.used > self.capacity:
            self._evict_one(evicted)
        return evicted
