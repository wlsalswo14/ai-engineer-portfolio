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
        self.target = self.capacity_bytes // 2
        self.ghost_limit = 4096

    def _drop_ghost(self, key):
        self.recent_ghost.pop(key, None)
        self.frequent_ghost.pop(key, None)

    def _remember(self, ghost, key, size):
        self._drop_ghost(key)
        ghost[key] = max(1, int(size))
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _remove_live(self, key):
        if key in self.recent:
            size = self.recent.pop(key)
            self.recent_bytes -= size
            return size, 1
        if key in self.frequent:
            size = self.frequent.pop(key)
            self.frequent_bytes -= size
            return size, 2
        return None, None

    def _evict_one(self, frequent_ghost_hit):
        prefer_recent = self.recent_bytes > self.target
        if frequent_ghost_hit and self.recent_bytes >= self.target:
            prefer_recent = True
        if prefer_recent and self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self._remember(self.recent_ghost, key, size)
            return key
        if self.frequent:
            key, size = self.frequent.popitem(last=False)
            self.frequent_bytes -= size
            self._remember(self.frequent_ghost, key, size)
            return key
        if self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self._remember(self.recent_ghost, key, size)
            return key
        return None

    def _make_room(self, size, frequent_ghost_hit):
        evicted = []
        while self.recent_bytes + self.frequent_bytes + size > self.capacity_bytes:
            key = self._evict_one(frequent_ghost_hit)
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

        if requested > self.capacity_bytes:
            old_size, segment = self._remove_live(key)
            if segment == 1:
                self._remember(self.recent_ghost, key, old_size)
                return [key]
            if segment == 2:
                self._remember(self.frequent_ghost, key, old_size)
                return [key]
            self._drop_ghost(key)
            return []

        old_size, segment = self._remove_live(key)
        if segment is not None:
            evicted = self._make_room(requested, False)
            self.frequent[key] = requested
            self.frequent_bytes += requested
            return evicted

        recent_ghost_hit = key in self.recent_ghost
        frequent_ghost_hit = key in self.frequent_ghost
        step = max(1, self.capacity_bytes // 16)
        if recent_ghost_hit:
            self.target = min(
                self.capacity_bytes,
                self.target + max(step, min(requested, self.capacity_bytes)),
            )
        elif frequent_ghost_hit:
            self.target = max(
                0,
                self.target - max(step, min(requested, self.capacity_bytes)),
            )

        self._drop_ghost(key)
        evicted = self._make_room(requested, frequent_ghost_hit)
        if recent_ghost_hit or frequent_ghost_hit:
            self.frequent[key] = requested
            self.frequent_bytes += requested
        else:
            self.recent[key] = requested
            self.recent_bytes += requested
        return evicted
