from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        try:
            capacity = int(capacity_bytes)
        except (TypeError, ValueError):
            capacity = 0
        self.capacity_bytes = max(0, capacity)
        self.recent = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.recent_bytes = 0
        self.protected_bytes = 0
        self.used_bytes = 0
        if self.capacity_bytes:
            self.protected_target = max(1, (self.capacity_bytes * 2) // 3)
        else:
            self.protected_target = 0
        self.adjustment = max(1, self.capacity_bytes // 16)

    def _forget_ghost(self, key):
        size = self.ghost_recent.pop(key, None)
        if size is not None:
            self.ghost_recent_bytes -= size
        size = self.ghost_protected.pop(key, None)
        if size is not None:
            self.ghost_protected_bytes -= size

    def _remember_ghost(self, segment, key, size):
        self._forget_ghost(key)
        if segment == 0:
            self.ghost_recent[key] = size
            self.ghost_recent_bytes += size
        else:
            self.ghost_protected[key] = size
            self.ghost_protected_bytes += size
        limit = max(1, self.capacity_bytes * 2)
        while self.ghost_recent_bytes + self.ghost_protected_bytes > limit:
            if self.ghost_recent:
                _, old_size = self.ghost_recent.popitem(last=False)
                self.ghost_recent_bytes -= old_size
            elif self.ghost_protected:
                _, old_size = self.ghost_protected.popitem(last=False)
                self.ghost_protected_bytes -= old_size
            else:
                break

    def _rebalance(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.recent[key] = size
            self.recent_bytes += size

    def _adjust_for_ghost(self, segment):
        if segment == 0:
            self.protected_target = max(0, self.protected_target - self.adjustment)
        else:
            self.protected_target = min(self.capacity_bytes, self.protected_target + self.adjustment)
        self._rebalance()

    def _evict_one(self):
        if self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self.used_bytes -= size
            self._remember_ghost(0, key, size)
            return key
        if self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.used_bytes -= size
            self._remember_ghost(1, key, size)
            return key
        return None

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.recent:
            stored_size = self.recent.pop(key)
            self.recent_bytes -= stored_size
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            self._rebalance()
            return []

        try:
            request_size = int(size)
        except (TypeError, ValueError):
            return []
        if request_size <= 0 or request_size > self.capacity_bytes:
            return []

        ghost_segment = None
        if key in self.ghost_recent:
            ghost_segment = 0
        elif key in self.ghost_protected:
            ghost_segment = 1
        if ghost_segment is not None:
            self._forget_ghost(key)
            self._adjust_for_ghost(ghost_segment)

        evicted = []
        while self.used_bytes + request_size > self.capacity_bytes:
            victim = self._evict_one()
            if victim is None:
                break
            evicted.append(victim)

        if ghost_segment is not None:
            self.protected[key] = request_size
            self.protected_bytes += request_size
            self.used_bytes += request_size
            self._rebalance()
        else:
            self.recent[key] = request_size
            self.recent_bytes += request_size
            self.used_bytes += request_size
        return evicted
