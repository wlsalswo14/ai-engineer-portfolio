from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.ghost_limit = 4096
        self.recent_target = self.capacity_bytes // 2
        self.used_bytes = 0
        self.recent_bytes = 0
        self.frequent_bytes = 0

    def _remember(self, ghost, key, size):
        ghost.pop(key, None)
        ghost[key] = size
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _discard_ghost(self, key):
        self.ghost_recent.pop(key, None)
        self.ghost_frequent.pop(key, None)

    def _evict_one(self):
        if self.recent and (self.recent_bytes > self.recent_target or not self.frequent):
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self._remember(self.ghost_recent, key, size)
        elif self.frequent:
            key, size = self.frequent.popitem(last=False)
            self.frequent_bytes -= size
            self._remember(self.ghost_frequent, key, size)
        elif self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self._remember(self.ghost_recent, key, size)
        else:
            return None
        self.used_bytes -= size
        return key

    def _adapt(self, key, size):
        if key in self.ghost_recent:
            pressure = max(1, len(self.ghost_frequent) // max(1, len(self.ghost_recent)))
            delta = max(self.capacity_bytes // 16, min(size, self.capacity_bytes) * pressure)
            self.recent_target = min(self.capacity_bytes, self.recent_target + delta)
        elif key in self.ghost_frequent:
            pressure = max(1, len(self.ghost_recent) // max(1, len(self.ghost_frequent)))
            delta = max(self.capacity_bytes // 16, min(size, self.capacity_bytes) * pressure)
            self.recent_target = max(0, self.recent_target - delta)

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.frequent:
            stored = self.frequent.pop(key)
            self.frequent[key] = stored
            return []

        if key in self.recent:
            stored = self.recent.pop(key)
            self.recent_bytes -= stored
            self.frequent[key] = stored
            self.frequent_bytes += stored
            return []

        if self.capacity_bytes == 0 or size <= 0 or size > self.capacity_bytes:
            return []

        self._adapt(key, size)
        self._discard_ghost(key)
        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._evict_one()
            if old_key is None:
                break
            evicted.append(old_key)

        self.recent[key] = int(size)
        self.recent_bytes += int(size)
        self.used_bytes += int(size)
        return evicted
