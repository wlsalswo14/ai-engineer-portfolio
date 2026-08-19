from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.used_bytes = 0
        self.ghost = OrderedDict()
        self.frequency = {}
        self.operations = 0
        self.ghost_limit = 4096

    def _bump(self, key):
        self.frequency[key] = self.frequency.get(key, 0) + 1
        self.operations += 1
        if self.operations >= 2048:
            self.operations = 0
            for item in list(self.frequency):
                value = (self.frequency[item] + 1) // 2
                if value:
                    self.frequency[item] = value
                else:
                    del self.frequency[item]

    def _remember_ghost(self, key):
        self.ghost.pop(key, None)
        self.ghost[key] = None
        while len(self.ghost) > self.ghost_limit:
            self.ghost.popitem(last=False)

    def _demote_protected(self):
        target = self.capacity_bytes // 2
        protected_bytes = sum(self.protected.values())
        while self.protected and protected_bytes > target:
            key, size = self.protected.popitem(last=False)
            protected_bytes -= size
            self.probation[key] = size

    def _oldest_victim(self):
        if self.probation:
            return next(iter(self.probation.items()))
        if self.protected:
            return next(iter(self.protected.items()))
        return None

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            self._bump(key)
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.protected[key] = stored_size
            self._bump(key)
            self._demote_protected()
            return []

        item_size = max(0, size)
        self._bump(key)

        if item_size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        was_ghost = key in self.ghost
        candidate_frequency = self.frequency.get(key, 1)
        evicted = []

        while self.used_bytes + item_size > self.capacity_bytes:
            victim = self._oldest_victim()
            if victim is None:
                break

            victim_key, victim_size = victim
            victim_frequency = self.frequency.get(victim_key, 1)
            if candidate_frequency <= victim_frequency and not was_ghost:
                return []
            if candidate_frequency * victim_size < victim_frequency * item_size:
                return []

            if self.probation:
                old_key, old_size = self.probation.popitem(last=False)
            else:
                old_key, old_size = self.protected.popitem(last=False)
            self.used_bytes -= old_size
            self._remember_ghost(old_key)
            evicted.append(old_key)

        self.ghost.pop(key, None)
        self.probation[key] = item_size
        self.used_bytes += item_size
        self._demote_protected()
        return evicted
