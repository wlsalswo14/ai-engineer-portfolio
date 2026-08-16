from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        self.capacity = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.used = 0
        self.protected_target = (self.capacity * 2) // 3
        self.ghosts = OrderedDict()
        self.ghost_bytes = 0
        self.ghost_probation_bytes = 0
        self.ghost_protected_bytes = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096

    def _drop_ghost(self, key):
        value = self.ghosts.pop(key, None)
        if value is None:
            return
        kind, size = value
        self.ghost_bytes -= size
        if kind == 1:
            self.ghost_probation_bytes -= size
        else:
            self.ghost_protected_bytes -= size

    def _remember_ghost(self, key, size, kind):
        self._drop_ghost(key)
        size = max(1, int(size))
        self.ghosts[key] = (kind, size)
        self.ghost_bytes += size
        if kind == 1:
            self.ghost_probation_bytes += size
        else:
            self.ghost_protected_bytes += size
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghosts) > self.ghost_count_limit):
            old_key, (old_kind, old_size) = self.ghosts.popitem(last=False)
            self.ghost_bytes -= old_size
            if old_kind == 1:
                self.ghost_probation_bytes -= old_size
            else:
                self.ghost_protected_bytes -= old_size

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        if kind == 1:
            left = self.ghost_probation_bytes
            right = self.ghost_protected_bytes
            delta = self.capacity if left == 0 else max(1, min(self.capacity, right // left or 1))
            self.protected_target = max(0, self.protected_target - delta)
        else:
            left = self.ghost_protected_bytes
            right = self.ghost_probation_bytes
            delta = self.capacity if left == 0 else max(1, min(self.capacity, right // left or 1))
            self.protected_target = min(self.capacity, self.protected_target + delta)

    def _remove_resident(self, key):
        value = self.probation.pop(key, None)
        if value is not None:
            self.probation_bytes -= value
            self.used -= value
            return value, 1
        value = self.protected.pop(key, None)
        if value is not None:
            self.protected_bytes -= value
            self.used -= value
            return value, 2
        return 0, 0

    def _demote_one(self):
        if not self.protected:
            return False
        key, size = self.protected.popitem(last=False)
        self.protected_bytes -= size
        self.probation[key] = size
        self.probation_bytes += size
        return True

    def _rebalance_protected(self):
        while self.protected and self.protected_bytes > self.protected_target:
            self._demote_one()

    def _evict_one(self):
        if not self.probation:
            if not self._demote_one():
                return None
        key, size = self.probation.popitem(last=False)
        self.probation_bytes -= size
        self.used -= size
        self._remember_ghost(key, size, 1)
        return key

    def _make_room(self, incoming):
        evicted = []
        while self.used + incoming > self.capacity:
            key = self._evict_one()
            if key is None:
                break
            evicted.append(key)
        return evicted

    def _insert(self, key, size, kind):
        self._drop_ghost(key)
        if kind == 2:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.probation[key] = size
            self.probation_bytes += size
        self.used += size
        self._rebalance_protected()

    def access(self, key, size, now):
        key = int(key)
        size = max(0, int(size))

        if key in self.protected:
            old_size, _ = self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size)
            if self.used + size > self.capacity:
                return evicted + [key]
            self._insert(key, size, 2)
            return evicted

        if key in self.probation:
            old_size, _ = self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size)
            if self.used + size > self.capacity:
                return evicted + [key]
            self._insert(key, size, 2)
            return evicted

        ghost = self.ghosts.get(key)
        ghost_kind = ghost[0] if ghost is not None else 0
        if ghost_kind:
            self._adjust_target(ghost_kind)
        if size <= 0 or size > self.capacity:
            return []

        evicted = self._make_room(size)
        if self.used + size > self.capacity:
            return evicted
        self._insert(key, size, 2 if ghost_kind == 2 else 1)
        return evicted
