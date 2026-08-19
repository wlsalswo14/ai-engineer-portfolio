from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.recent_ghost = OrderedDict()
        self.frequent_ghost = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0
        self.protected_target = self.capacity_bytes // 2
        self.ghost_limit = 1024

    def _remember(self, ghost, key):
        ghost.pop(key, None)
        ghost[key] = None
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _forget(self, key):
        self.recent_ghost.pop(key, None)
        self.frequent_ghost.pop(key, None)

    def _record_eviction(self, key, protected):
        self._forget(key)
        if protected:
            self._remember(self.frequent_ghost, key)
        else:
            self._remember(self.recent_ghost, key)

    def _demote_to_target(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size
            self.probation.move_to_end(key, last=False)

    def _evict_oldest(self, queue, protected):
        if not queue:
            return None
        key, size = queue.popitem(last=False)
        self.used_bytes -= size
        if protected:
            self.protected_bytes -= size
        self._record_eviction(key, protected)
        return key

    def _make_room(self, additional):
        evicted = []
        while self.used_bytes + additional > self.capacity_bytes:
            self._demote_to_target()
            victim = self._evict_oldest(self.probation, False)
            if victim is None:
                victim = self._evict_oldest(self.protected, True)
            if victim is None:
                break
            evicted.append(victim)
        return evicted

    def _adapt_target(self, key, size):
        step = max(1, min(self.capacity_bytes, max(size, self.capacity_bytes // 16)))
        if key in self.frequent_ghost:
            self.protected_target = min(self.capacity_bytes, self.protected_target + step)
        elif key in self.recent_ghost:
            self.protected_target = max(0, self.protected_target - step)
        self._demote_to_target()

    def access(self, key: int, size: int, now: int) -> list[int]:
        size = max(0, int(size))

        if key in self.protected:
            old_size = self.protected.pop(key)
            if size > self.capacity_bytes:
                self.used_bytes -= old_size
                self.protected_bytes -= old_size
                self._record_eviction(key, True)
                return [key]
            self.protected[key] = size
            self.used_bytes += size - old_size
            self.protected_bytes += size - old_size
            evicted = self._make_room(0)
            self._demote_to_target()
            return evicted

        if key in self.probation:
            old_size = self.probation.pop(key)
            if size > self.capacity_bytes:
                self.used_bytes -= old_size
                self._record_eviction(key, False)
                return [key]
            self.used_bytes += size - old_size
            self.protected[key] = size
            self.protected_bytes += size
            evicted = self._make_room(0)
            self._demote_to_target()
            return evicted

        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            self._forget(key)
            return []

        ghost_hit = key in self.recent_ghost or key in self.frequent_ghost
        if ghost_hit:
            self._adapt_target(key, size)
        self._forget(key)

        evicted = self._make_room(size)
        if self.used_bytes + size <= self.capacity_bytes:
            if ghost_hit:
                self.protected[key] = size
                self.protected_bytes += size
            else:
                self.probation[key] = size
            self.used_bytes += size
            self._demote_to_target()
        return evicted
