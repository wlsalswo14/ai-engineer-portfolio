from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probationary = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probationary = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.ghost_limit = 4096
        self.protected_target = self.capacity_bytes // 2
        self.probationary_bytes = 0
        self.protected_bytes = 0
        self.used_bytes = 0

    def _forget_ghost(self, key):
        self.ghost_probationary.pop(key, None)
        self.ghost_protected.pop(key, None)

    def _remember_ghost(self, ghost, key):
        self._forget_ghost(key)
        ghost[key] = None
        while len(self.ghost_probationary) + len(self.ghost_protected) > self.ghost_limit:
            if self.ghost_probationary:
                self.ghost_probationary.popitem(last=False)
            elif self.ghost_protected:
                self.ghost_protected.popitem(last=False)
            else:
                break

    def _demote(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probationary[key] = size
            self.probationary.move_to_end(key, last=False)
            self.probationary_bytes += size

    def _evict_one(self):
        if self.probationary and (
            not self.protected or self.probationary_bytes > self.protected_target
        ):
            key, size = self.probationary.popitem(last=False)
            self.probationary_bytes -= size
            self._remember_ghost(self.ghost_probationary, key)
        elif self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self._remember_ghost(self.ghost_protected, key)
        elif self.probationary:
            key, size = self.probationary.popitem(last=False)
            self.probationary_bytes -= size
            self._remember_ghost(self.ghost_probationary, key)
        else:
            return None
        self.used_bytes -= size
        return key

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.probationary:
            stored_size = self.probationary.pop(key)
            self.probationary_bytes -= stored_size
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            self._demote()
            return []

        requested_size = int(size)
        if (
            requested_size <= 0
            or requested_size > self.capacity_bytes
            or self.capacity_bytes == 0
        ):
            self._forget_ghost(key)
            return []

        step = max(1, self.capacity_bytes // 16)
        delta = max(step, min(requested_size, self.capacity_bytes))
        if key in self.ghost_probationary:
            self.protected_target = min(
                self.capacity_bytes, self.protected_target + delta
            )
        elif key in self.ghost_protected:
            self.protected_target = max(0, self.protected_target - delta)
        self._forget_ghost(key)
        self._demote()

        evicted = []
        while self.used_bytes + requested_size > self.capacity_bytes:
            victim = self._evict_one()
            if victim is None:
                break
            evicted.append(victim)

        if self.used_bytes + requested_size <= self.capacity_bytes:
            self.probationary[key] = requested_size
            self.probationary_bytes += requested_size
            self.used_bytes += requested_size
            self._demote()

        return evicted
