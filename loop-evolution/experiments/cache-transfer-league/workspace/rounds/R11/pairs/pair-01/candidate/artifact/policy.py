from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.used_bytes = 0
        self.recent_bytes = 0
        self.protected_bytes = 0
        self.recent_target = self.capacity_bytes // 3
        self.recent = OrderedDict()
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.ghost_limit = 2048

    def _recent_bounds(self):
        if self.capacity_bytes <= 0:
            return 0, 0
        minimum = max(1, self.capacity_bytes // 8)
        maximum = max(minimum, self.capacity_bytes - minimum)
        return minimum, maximum

    def _protected_target(self):
        return max(0, (self.capacity_bytes - self.recent_target) // 2)

    def _remove_ghost(self, key):
        self.ghost_recent.pop(key, None)
        self.ghost_frequent.pop(key, None)

    def _remember(self, key, size, frequent):
        self._remove_ghost(key)
        target = self.ghost_frequent if frequent else self.ghost_recent
        target[key] = size
        while len(self.ghost_recent) + len(self.ghost_frequent) > self.ghost_limit:
            if self.ghost_recent:
                self.ghost_recent.popitem(last=False)
            elif self.ghost_frequent:
                self.ghost_frequent.popitem(last=False)
            else:
                break

    def _adjust_target(self, key):
        if self.capacity_bytes <= 0:
            return False
        if key in self.ghost_recent:
            size = self.ghost_recent[key]
            delta = max(1, min(self.capacity_bytes, int(size)))
            self.recent_target += delta
            self._remove_ghost(key)
            return False
        if key in self.ghost_frequent:
            size = self.ghost_frequent[key]
            delta = max(1, min(self.capacity_bytes, int(size)))
            self.recent_target -= delta
            self._remove_ghost(key)
            return True
        return False

    def _evict_one(self, evicted):
        if self.probation:
            key, size = self.probation.popitem(last=False)
            frequent = True
        elif self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            frequent = False
        elif self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            frequent = True
        else:
            return False
        self.used_bytes -= size
        self._remember(key, size, frequent)
        evicted.append(key)
        return True

    def _make_room(self, size, evicted):
        while self.used_bytes + size > self.capacity_bytes:
            if not self._evict_one(evicted):
                return False
        return True

    def _rebalance(self):
        minimum, maximum = self._recent_bounds()
        if self.capacity_bytes > 0:
            self.recent_target = max(minimum, min(maximum, self.recent_target))
        while self.recent_bytes > self.recent_target and self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self.probation[key] = size
        target = self._protected_target()
        while self.protected_bytes > target and self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored = self.protected.pop(key)
            self.protected[key] = stored
            return []

        if key in self.probation:
            stored = self.probation.pop(key)
            self.protected[key] = stored
            self.protected_bytes += stored
            self._rebalance()
            return []

        if key in self.recent:
            stored = self.recent.pop(key)
            self.recent[key] = stored
            return []

        size = int(size)
        if self.capacity_bytes == 0 or size <= 0 or size > self.capacity_bytes:
            return []

        frequent_hint = self._adjust_target(key)
        evicted = []
        if not self._make_room(size, evicted):
            return evicted

        self.used_bytes += size
        if frequent_hint:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.recent[key] = size
            self.recent_bytes += size
        self._rebalance()
        return evicted
