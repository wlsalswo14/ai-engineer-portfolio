from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.used_bytes = 0
        self.recent_target = self.capacity_bytes // 2

    def _remember(self, key, size, frequent):
        self.ghost_recent.pop(key, None)
        self.ghost_frequent.pop(key, None)
        target = self.ghost_frequent if frequent else self.ghost_recent
        target[key] = size
        limit = max(64, min(4096, 2 * (len(self.recent) + len(self.frequent) + 1)))
        while len(self.ghost_recent) + len(self.ghost_frequent) > limit:
            if self.ghost_recent and (not self.ghost_frequent or len(self.ghost_recent) >= len(self.ghost_frequent)):
                self.ghost_recent.popitem(last=False)
            elif self.ghost_frequent:
                self.ghost_frequent.popitem(last=False)
            else:
                break

    def _promote(self, key):
        size = self.recent.pop(key)
        self.recent_bytes -= size
        self.frequent[key] = size
        self.frequent_bytes += size

    def _victim(self):
        if self.recent and (self.recent_bytes > self.recent_target or not self.frequent):
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            return key, size, False
        if self.frequent:
            key, size = self.frequent.popitem(last=False)
            self.frequent_bytes -= size
            return key, size, True
        if self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            return key, size, False
        return None

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.frequent:
            stored_size = self.frequent.pop(key)
            self.frequent[key] = stored_size
            return []

        if key in self.recent:
            self._promote(key)
            return []

        size = max(0, int(size))
        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        if key in self.ghost_recent:
            old_size = self.ghost_recent.pop(key)
            step = max(1, min(self.capacity_bytes, max(size, old_size)))
            self.recent_target = min(self.capacity_bytes, self.recent_target + step)
            self.ghost_frequent.pop(key, None)
        elif key in self.ghost_frequent:
            old_size = self.ghost_frequent.pop(key)
            step = max(1, min(self.capacity_bytes, max(size, old_size)))
            self.recent_target = max(0, self.recent_target - step)
            self.ghost_recent.pop(key, None)

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            victim = self._victim()
            if victim is None:
                break
            old_key, old_size, was_frequent = victim
            self.used_bytes -= old_size
            evicted.append(old_key)
            self._remember(old_key, old_size, was_frequent)

        self.recent[key] = size
        self.recent_bytes += size
        self.used_bytes += size
        return evicted
