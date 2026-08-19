from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.recent_ghost = OrderedDict()
        self.frequent_ghost = OrderedDict()
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.recent_ghost_bytes = 0
        self.frequent_ghost_bytes = 0
        self.used_bytes = 0
        self.target_recent = self.capacity_bytes // 2
        self.ghost_limit = self.capacity_bytes * 2
        self.ghost_entry_limit = (max(32, min(8192, self.capacity_bytes + 1)) if self.capacity_bytes else 0)

    def _discard_ghost(self, ghosts, key):
        if key not in ghosts:
            return 0
        size = ghosts.pop(key)
        if ghosts is self.recent_ghost:
            self.recent_ghost_bytes -= size
        else:
            self.frequent_ghost_bytes -= size
        return size

    def _remember_ghost(self, ghosts, key, size):
        self._discard_ghost(self.recent_ghost, key)
        self._discard_ghost(self.frequent_ghost, key)
        ghosts[key] = size
        if ghosts is self.recent_ghost:
            self.recent_ghost_bytes += size
        else:
            self.frequent_ghost_bytes += size
        while (self.recent_ghost_bytes + self.frequent_ghost_bytes > self.ghost_limit or
               len(self.recent_ghost) + len(self.frequent_ghost) > self.ghost_entry_limit):
            if self.recent_ghost and (not self.frequent_ghost or
                                      len(self.recent_ghost) >= len(self.frequent_ghost)):
                _, old_size = self.recent_ghost.popitem(last=False)
                self.recent_ghost_bytes -= old_size
            elif self.frequent_ghost:
                _, old_size = self.frequent_ghost.popitem(last=False)
                self.frequent_ghost_bytes -= old_size
            else:
                break

    def _evict_recent(self):
        key, size = self.recent.popitem(last=False)
        self.recent_bytes -= size
        self.used_bytes -= size
        self._remember_ghost(self.recent_ghost, key, size)
        return key

    def _evict_frequent(self):
        key, size = self.frequent.popitem(last=False)
        self.frequent_bytes -= size
        self.used_bytes -= size
        self._remember_ghost(self.frequent_ghost, key, size)
        return key

    def _make_room(self, size, evicted):
        while self.used_bytes + size > self.capacity_bytes:
            if self.recent and (self.recent_bytes > self.target_recent or not self.frequent):
                evicted.append(self._evict_recent())
            elif self.frequent:
                evicted.append(self._evict_frequent())
            elif self.recent:
                evicted.append(self._evict_recent())
            else:
                break

    def access(self, key: int, size: int, now: int) -> list[int]:
        requested_size = max(0, int(size))

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

        if self.capacity_bytes == 0 or requested_size > self.capacity_bytes:
            return []

        evicted = []

        if key in self.recent_ghost:
            self._discard_ghost(self.recent_ghost, key)
            delta = max(1, min(self.capacity_bytes,
                               max(requested_size, self.capacity_bytes // 32)))
            self.target_recent = min(self.capacity_bytes, self.target_recent + delta)
            self._make_room(requested_size, evicted)
            self.frequent[key] = requested_size
            self.frequent_bytes += requested_size
            self.used_bytes += requested_size
            return evicted

        if key in self.frequent_ghost:
            self._discard_ghost(self.frequent_ghost, key)
            delta = max(1, min(self.capacity_bytes,
                               max(requested_size, self.capacity_bytes // 32)))
            self.target_recent = max(0, self.target_recent - delta)
            self._make_room(requested_size, evicted)
            self.frequent[key] = requested_size
            self.frequent_bytes += requested_size
            self.used_bytes += requested_size
            return evicted

        self._make_room(requested_size, evicted)
        self.recent[key] = requested_size
        self.recent_bytes += requested_size
        self.used_bytes += requested_size
        return evicted
