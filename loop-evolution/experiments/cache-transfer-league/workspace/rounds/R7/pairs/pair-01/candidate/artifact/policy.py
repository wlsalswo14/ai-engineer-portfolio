from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.used_bytes = 0
        self.recent_limit = max(1, self.capacity_bytes // 4) if self.capacity_bytes else 0
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.ghost_limit = 4096
        self.max_items = 4096

    def _remember(self, ghost, key):
        ghost.pop(key, None)
        ghost[key] = None
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _remove_recent(self, key, evicted=None):
        size = self.recent.pop(key, None)
        if size is not None:
            self.used_bytes -= size
            self._remember(self.ghost_recent, key)
            if evicted is not None:
                evicted.append(key)
            return True
        return False

    def _remove_frequent(self, key, evicted=None):
        size = self.frequent.pop(key, None)
        if size is not None:
            self.used_bytes -= size
            self._remember(self.ghost_frequent, key)
            if evicted is not None:
                evicted.append(key)
            return True
        return False

    def _trim_recent(self, evicted):
        while (len(self.recent) > 1 and
               sum(self.recent.values()) > self.recent_limit):
            key = next(iter(self.recent))
            self._remove_recent(key, evicted)

    def _trim_frequent(self, evicted):
        frequent_limit = self.capacity_bytes - self.recent_limit
        while (len(self.frequent) > 1 and
               sum(self.frequent.values()) > frequent_limit):
            key = next(iter(self.frequent))
            self._remove_frequent(key, evicted)

    def _trim_count(self, evicted):
        while len(self.recent) + len(self.frequent) > self.max_items:
            if self.recent:
                self._remove_recent(next(iter(self.recent)), evicted)
            elif self.frequent:
                self._remove_frequent(next(iter(self.frequent)), evicted)
            else:
                break

    def _make_room(self, size, evicted):
        while self.used_bytes + size > self.capacity_bytes:
            if self.recent:
                self._remove_recent(next(iter(self.recent)), evicted)
            elif self.frequent:
                self._remove_frequent(next(iter(self.frequent)), evicted)
            else:
                break

    def _adapt(self, key):
        step = max(1, self.capacity_bytes // 16)
        if key in self.ghost_recent:
            self.recent_limit = min(self.capacity_bytes,
                                    self.recent_limit + step)
        elif key in self.ghost_frequent:
            self.recent_limit = max(1, self.recent_limit - step)

    def access(self, key: int, size: int, now: int) -> list[int]:
        _ = now
        if key in self.frequent:
            stored_size = self.frequent.pop(key)
            self.frequent[key] = stored_size
            return []

        if key in self.recent:
            stored_size = self.recent.pop(key)
            self.used_bytes -= stored_size
            self.frequent[key] = stored_size
            self.used_bytes += stored_size
            evicted = []
            self._trim_frequent(evicted)
            self._trim_count(evicted)
            return evicted

        if self.capacity_bytes == 0:
            return []

        size = max(0, size)
        if size > self.capacity_bytes:
            return []

        self._adapt(key)
        self.ghost_recent.pop(key, None)
        self.ghost_frequent.pop(key, None)

        evicted = []
        self._make_room(size, evicted)
        if self.used_bytes + size <= self.capacity_bytes:
            self.recent[key] = size
            self.used_bytes += size
            self._trim_recent(evicted)
            self._trim_frequent(evicted)
            self._trim_count(evicted)
        return evicted
