from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.used_bytes = 0
        self.frequent_target = self.capacity_bytes // 2
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.ghost_limit = 4096

    def _remember(self, ghost, key):
        ghost.pop(key, None)
        ghost[key] = None
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _forget(self, key):
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

        if size <= 0 or self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        step = max(1, self.capacity_bytes // 16)
        if key in self.ghost_recent:
            self.frequent_target = min(
                self.capacity_bytes,
                self.frequent_target + max(step, min(size, self.capacity_bytes)),
            )
        elif key in self.ghost_frequent:
            self.frequent_target = max(
                0,
                self.frequent_target - max(step, min(size, self.capacity_bytes)),
            )
        self._forget(key)
        self._rebalance()

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            victim = self._evict_one()
            if victim is None:
                break
            evicted.append(victim)

        self.recent[key] = size
        self.recent_bytes += size
        self.used_bytes += size
        return evicted
