from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.recent_ghost = OrderedDict()
        self.frequent_ghost = OrderedDict()
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.recent_ghost_bytes = 0
        self.frequent_ghost_bytes = 0
        self.used_bytes = 0
        self.recent_target = 0

    def _remove_ghost(self, key):
        if key in self.recent_ghost:
            self.recent_ghost_bytes -= self.recent_ghost.pop(key)
        if key in self.frequent_ghost:
            self.frequent_ghost_bytes -= self.frequent_ghost.pop(key)

    def _trim_ghosts(self):
        limit = max(1, len(self.recent) + len(self.frequent))
        while len(self.recent_ghost) + len(self.frequent_ghost) > limit:
            if self.recent_ghost and (not self.frequent_ghost or len(self.recent_ghost) >= len(self.frequent_ghost)):
                _, size = self.recent_ghost.popitem(last=False)
                self.recent_ghost_bytes -= size
            elif self.frequent_ghost:
                _, size = self.frequent_ghost.popitem(last=False)
                self.frequent_ghost_bytes -= size

    def _remember_ghost(self, key, size, recent):
        self._remove_ghost(key)
        if recent:
            self.recent_ghost[key] = size
            self.recent_ghost_bytes += size
        else:
            self.frequent_ghost[key] = size
            self.frequent_ghost_bytes += size
        self._trim_ghosts()

    def _evict_recent(self, evicted):
        key, size = self.recent.popitem(last=False)
        self.recent_bytes -= size
        self.used_bytes -= size
        evicted.append(key)
        self._remember_ghost(key, size, True)

    def _evict_frequent(self, evicted):
        key, size = self.frequent.popitem(last=False)
        self.frequent_bytes -= size
        self.used_bytes -= size
        evicted.append(key)
        self._remember_ghost(key, size, False)

    def _make_room(self, size, from_frequent_ghost):
        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            if self.recent and (self.recent_bytes > self.recent_target or (from_frequent_ghost and self.recent_bytes == self.recent_target)):
                self._evict_recent(evicted)
            elif self.frequent:
                self._evict_frequent(evicted)
            elif self.recent:
                self._evict_recent(evicted)
            else:
                break
        return evicted

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

        if size < 0 or self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        in_recent_ghost = key in self.recent_ghost
        in_frequent_ghost = key in self.frequent_ghost

        if in_recent_ghost:
            step = max(1, self.frequent_ghost_bytes // max(1, self.recent_ghost_bytes))
            self.recent_target = min(self.capacity_bytes, self.recent_target + step)
        elif in_frequent_ghost:
            step = max(1, self.recent_ghost_bytes // max(1, self.frequent_ghost_bytes))
            self.recent_target = max(0, self.recent_target - step)

        self._remove_ghost(key)
        evicted = self._make_room(size, in_frequent_ghost)
        self.recent[key] = size
        self.recent_bytes += size
        self.used_bytes += size
        self._trim_ghosts()
        return evicted
