from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.probationary = OrderedDict()
        self.protected = OrderedDict()
        self.ghost = OrderedDict()
        self.probationary_bytes = 0
        self.protected_bytes = 0
        self.used = 0
        self.target = self.capacity // 2
        self.ghost_bytes = 0
        self.ghost_probationary_bytes = 0
        self.ghost_protected_bytes = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096

    def _remove_ghost(self, key):
        value = self.ghost.pop(key, None)
        if value is None:
            return
        size, kind = value
        self.ghost_bytes -= size
        if kind == 1:
            self.ghost_probationary_bytes -= size
        else:
            self.ghost_protected_bytes -= size

    def _remember_ghost(self, key, size, kind):
        self._remove_ghost(key)
        size = max(0, int(size))
        self.ghost[key] = (size, kind)
        self.ghost_bytes += size
        if kind == 1:
            self.ghost_probationary_bytes += size
        else:
            self.ghost_protected_bytes += size
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost) > self.ghost_count_limit):
            oldest = next(iter(self.ghost))
            self._remove_ghost(oldest)

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        if kind == 1:
            if self.ghost_probationary_bytes == 0:
                delta = self.capacity
            else:
                delta = max(1, min(
                    self.capacity,
                    self.ghost_protected_bytes // self.ghost_probationary_bytes or 1,
                ))
            self.target = min(self.capacity, self.target + delta)
        else:
            if self.ghost_protected_bytes == 0:
                delta = self.capacity
            else:
                delta = max(1, min(
                    self.capacity,
                    self.ghost_probationary_bytes // self.ghost_protected_bytes or 1,
                ))
            self.target = max(0, self.target - delta)

    def _remove_resident(self, key):
        size = self.probationary.pop(key, None)
        if size is not None:
            self.probationary_bytes -= size
            self.used -= size
            return size
        size = self.protected.pop(key, None)
        if size is not None:
            self.protected_bytes -= size
            self.used -= size
            return size
        return None

    def _evict_one(self, incoming_kind):
        if self.probationary and (
            self.probationary_bytes > self.target or
            incoming_kind in (1, 2) or
            not self.protected
        ):
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

    def _make_room(self, size, incoming_kind):
        evicted = []
        while self.used + size > self.capacity:
            key = self._evict_one(incoming_kind)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))

        if key in self.probationary or key in self.protected:
            self._remove_resident(key)
            if size > self.capacity:
                return [key]
            evicted = self._make_room(size, 2)
            self._remove_ghost(key)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            return evicted

        ghost_kind = 0
        value = self.ghost.get(key)
        if value is not None:
            ghost_kind = value[1]

        if size > self.capacity:
            return []

        if ghost_kind:
            self._adjust_target(ghost_kind)
            self._remove_ghost(key)

        evicted = self._make_room(size, 2 if ghost_kind else 0)
        if ghost_kind:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.probationary[key] = size
            self.probationary_bytes += size
        self.used += size
        return evicted
