from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        self.capacity = capacity_bytes if isinstance(capacity_bytes, int) and not isinstance(capacity_bytes, bool) and capacity_bytes > 0 else 0
        self.used = 0
        self.probationary = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probationary = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.protected_target = self.capacity * 3 // 5
        self.clock = 0

    def _valid_key(self, key):
        return isinstance(key, int) and not isinstance(key, bool)

    def _remember_ghost(self, ghosts, key, size):
        ghosts.pop(key, None)
        ghosts[key] = size
        limit = max(64, min(4096, self.capacity // max(1, size) + 64))
        while len(ghosts) > limit:
            ghosts.popitem(last=False)

    def _remove_probationary(self, key, ghosts=None, evicted=None):
        item = self.probationary.pop(key, None)
        if item is not None:
            self.used -= item[0]
            if ghosts is not None:
                self._remember_ghost(ghosts, key, item[0])
            if evicted is not None:
                evicted.append(key)
        return item

    def _remove_protected(self, key, ghosts=None, evicted=None):
        item = self.protected.pop(key, None)
        if item is not None:
            self.used -= item[0]
            if ghosts is not None:
                self._remember_ghost(ghosts, key, item[0])
            if evicted is not None:
                evicted.append(key)
        return item

    def _rebalance_protected(self):
        while self.protected and sum(item[0] for item in self.protected.values()) > self.protected_target:
            key, item = self.protected.popitem(last=False)
            self.probationary[key] = item

    def _trim(self, evicted):
        while self.used > self.capacity:
            if self.probationary:
                key, item = self.probationary.popitem(last=False)
                self.used -= item[0]
                self._remember_ghost(self.ghost_probationary, key, item[0])
                evicted.append(key)
            elif self.protected:
                key, item = self.protected.popitem(last=False)
                self.used -= item[0]
                self._remember_ghost(self.ghost_protected, key, item[0])
                evicted.append(key)
            else:
                break

    def access(self, key, size, now):
        evicted = []
        self.clock += 1

        if not self._valid_key(key) or not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            return evicted

        if self.capacity == 0:
            for cached_key in list(self.probationary):
                self._remove_probationary(cached_key, evicted=evicted)
            for cached_key in list(self.protected):
                self._remove_protected(cached_key, evicted=evicted)
            return evicted

        if key in self.protected:
            old_size, hits, _ = self.protected.pop(key)
            self.used += size - old_size
            self.protected[key] = (size, hits + 1, self.clock)
            if self.used > self.capacity:
                self._remove_protected(key, ghosts=self.ghost_protected, evicted=evicted)
                self._trim(evicted)
            return evicted

        if key in self.probationary:
            old_size, hits, _ = self.probationary.pop(key)
            self.used += size - old_size
            if self.used > self.capacity:
                self.used -= size
                self._remember_ghost(self.ghost_probationary, key, size)
                evicted.append(key)
                self._trim(evicted)
                return evicted
            self.protected[key] = (size, hits + 1, self.clock)
            self._rebalance_protected()
            return evicted

        in_protected_ghost = key in self.ghost_protected
        in_probationary_ghost = key in self.ghost_probationary
        if in_protected_ghost:
            self.ghost_protected.pop(key, None)
            self.protected_target = min(self.capacity, self.protected_target + max(1, self.capacity // 16))
        elif in_probationary_ghost:
            self.ghost_probationary.pop(key, None)
            self.protected_target = max(0, self.protected_target - max(1, self.capacity // 16))

        if size > self.capacity:
            return evicted

        self.probationary[key] = (size, 1, self.clock)
        self.used += size
        self._trim(evicted)
        return evicted
