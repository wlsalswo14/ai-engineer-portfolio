from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self._probation = OrderedDict()
        self._protected = OrderedDict()
        self._ghost_probation = OrderedDict()
        self._ghost_protected = OrderedDict()
        self._used_bytes = 0
        self._protected_bytes = 0
        self._protected_limit = self.capacity_bytes // 2
        self._ghost_limit = 1024

    def _rebalance(self):
        while self._protected and self._protected_bytes > self._protected_limit:
            key, item_size = self._protected.popitem(last=False)
            self._protected_bytes -= item_size
            self._probation[key] = item_size

    def _remember(self, key, protected):
        self._ghost_probation.pop(key, None)
        self._ghost_protected.pop(key, None)
        ghost = self._ghost_protected if protected else self._ghost_probation
        ghost[key] = None
        while len(ghost) > self._ghost_limit:
            ghost.popitem(last=False)

    def _adapt(self, protected_ghost_hit):
        step = max(1, self.capacity_bytes // 8)
        if protected_ghost_hit:
            self._protected_limit = max(0, self._protected_limit - step)
        else:
            self._protected_limit = min(self.capacity_bytes, self._protected_limit + step)
        self._rebalance()

    def _evict_one(self):
        if self._probation:
            key, item_size = self._probation.popitem(last=False)
            self._remember(key, False)
        elif self._protected:
            key, item_size = self._protected.popitem(last=False)
            self._protected_bytes -= item_size
            self._remember(key, True)
        else:
            return None
        self._used_bytes -= item_size
        return key

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self._protected:
            item_size = self._protected.pop(key)
            self._protected[key] = item_size
            return []

        if key in self._probation:
            item_size = self._probation.pop(key)
            self._protected[key] = item_size
            self._protected_bytes += item_size
            self._rebalance()
            return []

        size = max(0, size)
        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        protected_ghost_hit = key in self._ghost_protected
        probation_ghost_hit = key in self._ghost_probation
        if protected_ghost_hit or probation_ghost_hit:
            self._ghost_protected.pop(key, None)
            self._ghost_probation.pop(key, None)
            self._adapt(protected_ghost_hit)

        evicted = []
        while self._used_bytes + size > self.capacity_bytes:
            victim = self._evict_one()
            if victim is None:
                break
            evicted.append(victim)

        if self._used_bytes + size > self.capacity_bytes:
            return evicted

        self._used_bytes += size
        if protected_ghost_hit:
            self._protected[key] = size
            self._protected_bytes += size
            self._rebalance()
        else:
            self._probation[key] = size
        return evicted
