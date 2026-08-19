from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.recent_ghost = OrderedDict()
        self.frequent_ghost = OrderedDict()
        self.ghost_order = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0
        self.protected_target = self.capacity_bytes // 2

    def _forget(self, key):
        self.recent_ghost.pop(key, None)
        self.frequent_ghost.pop(key, None)
        self.ghost_order.pop(key, None)

    def _remember(self, key, kind):
        self._forget(key)
        if kind == 'recent':
            self.recent_ghost[key] = None
        else:
            self.frequent_ghost[key] = None
        self.ghost_order[key] = kind

    def _trim_ghosts(self):
        limit = max(16, 2 * (len(self.probation) + len(self.protected) + 1))
        while len(self.ghost_order) > limit:
            key, kind = self.ghost_order.popitem(last=False)
            if kind == 'recent':
                self.recent_ghost.pop(key, None)
            else:
                self.frequent_ghost.pop(key, None)

    def _rebalance(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            self._rebalance()
            return []

        item_size = max(0, size)
        if self.capacity_bytes == 0 or item_size > self.capacity_bytes:
            return []

        ghost_kind = self.ghost_order.get(key)
        if ghost_kind == 'recent':
            self.protected_target = max(0, self.protected_target - item_size)
        elif ghost_kind == 'frequent':
            self.protected_target = min(self.capacity_bytes, self.protected_target + item_size)
        if ghost_kind is not None:
            self._forget(key)

        self._rebalance()
        evicted = []
        while self.used_bytes + item_size > self.capacity_bytes:
            if self.probation:
                old_key, old_size = self.probation.popitem(last=False)
                self._remember(old_key, 'recent')
            elif self.protected:
                old_key, old_size = self.protected.popitem(last=False)
                self.protected_bytes -= old_size
                self._remember(old_key, 'frequent')
            else:
                break
            self.used_bytes -= old_size
            evicted.append(old_key)

        if ghost_kind is not None:
            self.protected[key] = item_size
            self.protected_bytes += item_size
        else:
            self.probation[key] = item_size
        self.used_bytes += item_size
        self._rebalance()
        self._trim_ghosts()
        return evicted
