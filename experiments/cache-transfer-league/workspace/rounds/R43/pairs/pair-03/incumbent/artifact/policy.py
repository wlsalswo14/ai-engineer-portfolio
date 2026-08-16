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

    def _evict_from(self, cache, ghost, frequent):
        if not cache:
            return None
        key, size = cache.popitem(last=False)
        if frequent:
            self.frequent_bytes -= size
        else:
            self.recent_bytes -= size
        self.used_bytes -= size
        self._remember(ghost, key)
        return key

    def _replace(self):
        if self.recent and (self.recent_bytes > self.recent_target or not self.frequent):
            return self._evict_from(self.recent, self.ghost_recent, False)
        if self.frequent:
            return self._evict_from(self.frequent, self.ghost_frequent, True)
        if self.recent:
            return self._evict_from(self.recent, self.ghost_recent, False)
        return None

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
            return []

        if size <= 0 or self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        step = max(1, self.capacity_bytes // 16)
        adjustment = max(step, min(size, self.capacity_bytes))
        if key in self.ghost_recent:
            self.recent_target = min(
                self.capacity_bytes,
                self.recent_target + adjustment,
            )
        elif key in self.ghost_frequent:
            self.recent_target = max(0, self.recent_target - adjustment)
        self._forget_ghost(key)

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._replace()
            if old_key is None:
                return evicted
            evicted.append(old_key)

        self.recent[key] = size
        self.recent_bytes += size
        self.used_bytes += size
        return evicted
