from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.target = self.capacity // 2
        self.recent_bytes = 0
        self.frequent_bytes = 0

    def _forget_ghost(self, key):
        self.ghost_recent.pop(key, None)
        self.ghost_frequent.pop(key, None)

    def _remember(self, ghost, key, size):
        self._forget_ghost(key)
        if self.capacity <= 0:
            return
        ghost[key] = int(size)
        while len(ghost) > 4096:
            ghost.popitem(last=False)

    def _remove_resident(self, key):
        if key in self.recent:
            size = self.recent.pop(key)
            self.recent_bytes -= size
            return size
        if key in self.frequent:
            size = self.frequent.pop(key)
            self.frequent_bytes -= size
            return size
        return None

    def _evict_one(self, frequent_hit):
        take_recent = bool(self.recent) and (
            self.recent_bytes > self.target
            or (frequent_hit and self.recent_bytes == self.target)
        )
        if take_recent:
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

    def _make_room(self, size, frequent_hit):
        evicted = []
        while self.recent_bytes + self.frequent_bytes + size > self.capacity:
            key = self._evict_one(frequent_hit)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        requested = int(size)

        if requested <= 0:
            if key in self.recent:
                self.recent.move_to_end(key)
            elif key in self.frequent:
                self.frequent.move_to_end(key)
            return []

        if requested > self.capacity:
            if key in self.recent:
                old = self.recent.pop(key)
                self.recent_bytes -= old
                self._remember(self.ghost_recent, key, old)
                return [key]
            if key in self.frequent:
                old = self.frequent.pop(key)
                self.frequent_bytes -= old
                self._remember(self.ghost_frequent, key, old)
                return [key]
            return []

        if key in self.recent or key in self.frequent:
            self._remove_resident(key)
            self._forget_ghost(key)
            evicted = self._make_room(requested, False)
            self.frequent[key] = requested
            self.frequent_bytes += requested
            return evicted

        recent_hit = key in self.ghost_recent
        frequent_hit = key in self.ghost_frequent
        if recent_hit:
            step = max(1, min(requested, self.capacity))
            self.target = min(self.capacity, self.target + step)
        elif frequent_hit:
            step = max(1, min(requested, self.capacity))
            self.target = max(0, self.target - step)

        self._forget_ghost(key)
        evicted = self._make_room(requested, frequent_hit)
        if recent_hit or frequent_hit:
            self.frequent[key] = requested
            self.frequent_bytes += requested
        else:
            self.recent[key] = requested
            self.recent_bytes += requested
        return evicted
