from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.used = 0
        self.sequence = 0
        self.items = {}
        self.ghost = {}
        self.ghost_order = OrderedDict()
        self.ghost_limit = 4096
        self.protected_limit = (self.capacity * 3) // 4
        self.protected_used = 0

    def _remember(self, key):
        count = min(31, self.ghost.get(key, 0) + 1)
        self.ghost[key] = count
        self.ghost_order.pop(key, None)
        self.ghost_order[key] = None
        while len(self.ghost_order) > self.ghost_limit:
            old, _ = self.ghost_order.popitem(last=False)
            self.ghost.pop(old, None)

    def _demote_oldest_protected(self):
        protected = [(k, v) for k, v in self.items.items() if v[4]]
        if not protected:
            return False
        key, entry = min(protected, key=lambda pair: (pair[1][2], pair[1][3], pair[0]))
        entry[4] = False
        self.protected_used -= entry[0]
        return True

    def _promote(self, key):
        entry = self.items[key]
        if entry[4] or entry[0] > self.protected_limit:
            return
        while self.protected_used + entry[0] > self.protected_limit:
            if not self._demote_oldest_protected():
                break
        if self.protected_used + entry[0] <= self.protected_limit:
            entry[4] = True
            self.protected_used += entry[0]

    def _victim(self, exclude=None):
        probation = [(k, v) for k, v in self.items.items()
                     if not v[4] and k != exclude]
        pool = probation
        if not pool:
            pool = [(k, v) for k, v in self.items.items() if k != exclude]
        if not pool:
            return None
        return min(pool, key=lambda pair: (pair[1][1], pair[1][3], pair[1][2], -pair[1][0], pair[0]))[0]

    def _remove(self, key):
        entry = self.items.pop(key)
        self.used -= entry[0]
        if entry[4]:
            self.protected_used -= entry[0]
        self._remember(key)

    def access(self, key: int, size: int, now: int) -> list[int]:
        self.sequence += 1
        evicted = []

        if key in self.items:
            entry = self.items[key]
            if size > 0 and size != entry[0]:
                self.used += size - entry[0]
                if entry[4]:
                    self.protected_used += size - entry[0]
                entry[0] = size
                while self.used > self.capacity:
                    victim = self._victim(exclude=key)
                    if victim is None:
                        break
                    evicted.append(victim)
                    self._remove(victim)
                if self.used > self.capacity:
                    evicted.append(key)
                    self._remove(key)
                    return evicted
            entry[1] = min(255, entry[1] + 1)
            entry[2] = self.sequence
            entry[3] = now
            self._promote(key)
            return evicted

        if self.capacity <= 0 or size <= 0:
            return evicted

        if size > self.capacity:
            for victim in sorted(self.items):
                evicted.append(victim)
            for victim in evicted:
                self._remove(victim)
            return evicted

        remembered = self.ghost.pop(key, 0)
        self.ghost_order.pop(key, None)
        while self.used + size > self.capacity:
            victim = self._victim()
            if victim is None:
                break
            evicted.append(victim)
            self._remove(victim)

        protected = remembered >= 2 and size <= self.protected_limit
        self.items[key] = [size, min(255, 1 + remembered), self.sequence, now, protected]
        self.used += size
        if protected:
            self.protected_used += size
            while self.protected_used > self.protected_limit:
                if not self._demote_oldest_protected():
                    break
        return evicted
