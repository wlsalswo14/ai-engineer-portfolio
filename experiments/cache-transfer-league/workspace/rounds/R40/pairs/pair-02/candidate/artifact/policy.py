from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.ghost_limit = max(128, min(8192, self.capacity_bytes // 64 + 128))
        self.frequent_target = self.capacity_bytes // 2
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.used_bytes = 0

    def _remember(self, ghost, key):
        ghost.pop(key, None)
        ghost[key] = None
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _forget_ghost(self, key):
        self.ghost_recent.pop(key, None)
        self.ghost_frequent.pop(key, None)

    def _rebalance(self):
        while self.frequent and self.frequent_bytes > self.frequent_target:
            key, size = self.frequent.popitem(last=False)
            self.frequent_bytes -= size
            self.recent[key] = size
            self.recent_bytes += size

    def _evict_one(self):
        if self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self._remember(self.ghost_recent, key)
        elif self.frequent:
            key, size = self.frequent.popitem(last=False)
            self.frequent_bytes -= size
            self._remember(self.ghost_frequent, key)
        else:
            return None
        self.used_bytes -= size
        return key

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.frequent:
            stored_size = self.frequent.pop(key)
            self.frequent[key] = stored_size
            return []

        if key in self.recent:
            stored_size = self.recent.pop(key)
            self.recent_bytes -= stored_size
            self.frequent[key] = stored_size
            self.frequent_bytes += stored_size
            self._rebalance()
            return []

        size = int(size)
        if size <= 0 or self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        step = max(1, self.capacity_bytes // 16)
        delta = max(step, min(size, self.capacity_bytes))
        if key in self.ghost_recent:
            self.frequent_target = min(self.capacity_bytes, self.frequent_target + delta)
        elif key in self.ghost_frequent:
            self.frequent_target = max(0, self.frequent_target - delta)
        self._forget_ghost(key)

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._evict_one()
            if old_key is None:
                break
            evicted.append(old_key)

        self.recent[key] = size
        self.recent_bytes += size
        self.used_bytes += size
        self._rebalance()
        return evicted
