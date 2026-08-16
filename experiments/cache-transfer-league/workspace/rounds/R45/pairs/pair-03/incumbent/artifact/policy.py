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

    def _remember(self, ghost, key, size):
        ghost.pop(key, None)
        ghost[key] = size
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _forget(self, key):
        self.ghost_recent.pop(key, None)
        self.ghost_frequent.pop(key, None)

    def _adjust_target(self, increase, size):
        if self.capacity_bytes == 0:
            return
        step = max(1, self.capacity_bytes // 16)
        delta = max(step, min(size, self.capacity_bytes))
        if increase:
            self.recent_target = min(
                self.capacity_bytes, self.recent_target + delta
            )
        else:
            self.recent_target = max(0, self.recent_target - delta)

    def _evict_one(self):
        if self.recent and (
            self.recent_bytes >= self.recent_target or not self.frequent
        ):
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self._remember(self.ghost_recent, key, size)
            return key
        if self.frequent:
            key, size = self.frequent.popitem(last=False)
            self.frequent_bytes -= size
            self._remember(self.ghost_frequent, key, size)
            return key
        if self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self._remember(self.ghost_recent, key, size)
            return key
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

        if key in self.ghost_recent:
            self._adjust_target(True, size)
        elif key in self.ghost_frequent:
            self._adjust_target(False, size)
        self._forget(key)

        evicted = []
        while self.recent_bytes + self.frequent_bytes + size > self.capacity_bytes:
            victim = self._evict_one()
            if victim is None:
                break
            evicted.append(victim)

        self.recent[key] = size
        self.recent_bytes += size
        return evicted
