from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.target_recent = 0
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.used = 0
        self.ghost_clock = 0
        self.ghost_limit = 4096

    def _remember(self, ghost, key, size):
        if self.capacity == 0:
            return
        self.ghost_recent.pop(key, None)
        self.ghost_frequent.pop(key, None)
        self.ghost_clock += 1
        ghost[key] = (size, self.ghost_clock)
        while len(self.ghost_recent) + len(self.ghost_frequent) > self.ghost_limit:
            if not self.ghost_recent:
                self.ghost_frequent.popitem(last=False)
            elif not self.ghost_frequent:
                self.ghost_recent.popitem(last=False)
            else:
                rk = next(iter(self.ghost_recent))
                fk = next(iter(self.ghost_frequent))
                if self.ghost_recent[rk][1] <= self.ghost_frequent[fk][1]:
                    self.ghost_recent.popitem(last=False)
                else:
                    self.ghost_frequent.popitem(last=False)

    def _remove(self, table, key, ghost):
        size = table.pop(key)
        self.used -= size
        self._remember(ghost, key, size)
        return size

    def _evict_one(self, prefer_recent):
        if prefer_recent and self.recent:
            table, ghost = self.recent, self.ghost_recent
        elif self.frequent:
            table, ghost = self.frequent, self.ghost_frequent
        elif self.recent:
            table, ghost = self.recent, self.ghost_recent
        else:
            return None
        key, size = table.popitem(last=False)
        self.used -= size
        self._remember(ghost, key, size)
        return key

    def _make_room(self, incoming, prefer_frequent):
        evicted = []
        while self.used + incoming > self.capacity and (self.recent or self.frequent):
            prefer_recent = bool(self.recent) and (
                self._recent_bytes() > self.target_recent
                or (prefer_frequent and self._recent_bytes() == self.target_recent)
            )
            key = self._evict_one(prefer_recent)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def _recent_bytes(self):
        return sum(self.recent.values())

    def _adjust_target(self, upward, amount):
        if self.capacity == 0:
            return
        delta = max(1, min(self.capacity, amount))
        if upward:
            self.target_recent = min(self.capacity, self.target_recent + delta)
        else:
            self.target_recent = max(0, self.target_recent - delta)

    def access(self, key: int, size: int, now: int) -> list[int]:
        try:
            size = max(0, int(size))
        except (TypeError, ValueError):
            size = 0

        if key in self.recent:
            old_size = self.recent.pop(key)
            self.used -= old_size
            if size > self.capacity:
                self._remember(self.ghost_recent, key, old_size)
                return [key]
            self.frequent[key] = size
            self.used += size
            return self._make_room(0, False)

        if key in self.frequent:
            old_size = self.frequent.pop(key)
            self.used -= old_size
            if size > self.capacity:
                self._remember(self.ghost_frequent, key, old_size)
                return [key]
            self.frequent[key] = size
            self.used += size
            return self._make_room(0, False)

        if self.capacity == 0 or size > self.capacity:
            return []

        if key in self.ghost_recent:
            old_size, _ = self.ghost_recent.pop(key)
            self._adjust_target(True, max(old_size, size))
            evicted = self._make_room(size, True)
            self.frequent[key] = size
            self.used += size
            return evicted

        if key in self.ghost_frequent:
            old_size, _ = self.ghost_frequent.pop(key)
            self._adjust_target(False, max(old_size, size))
            evicted = self._make_room(size, True)
            self.frequent[key] = size
            self.used += size
            return evicted

        evicted = self._make_room(size, False)
        self.recent[key] = size
        self.used += size
        return evicted
