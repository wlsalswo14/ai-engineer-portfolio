from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.ghost_recent_bytes = 0
        self.ghost_frequent_bytes = 0
        self.used = 0
        self.recent_target = self.capacity // 2
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096
        self.ghost_bytes = 0

    def _forget_ghost(self, key):
        value = self.ghost_recent.pop(key, None)
        if value is not None:
            self.ghost_recent_bytes -= value
            self.ghost_bytes -= value
        value = self.ghost_frequent.pop(key, None)
        if value is not None:
            self.ghost_frequent_bytes -= value
            self.ghost_bytes -= value

    def _remember_ghost(self, key, size, kind):
        self._forget_ghost(key)
        size = max(1, int(size))
        if kind == 1:
            self.ghost_recent[key] = size
            self.ghost_recent_bytes += size
        else:
            self.ghost_frequent[key] = size
            self.ghost_frequent_bytes += size
        self.ghost_bytes += size
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_recent) + len(self.ghost_frequent) > self.ghost_count_limit):
            recent_key = next(iter(self.ghost_recent), None)
            frequent_key = next(iter(self.ghost_frequent), None)
            if recent_key is None:
                old_key = frequent_key
                old_kind = 2
            elif frequent_key is None:
                old_key = recent_key
                old_kind = 1
            else:
                if self.ghost_recent[recent_key] <= self.ghost_frequent[frequent_key]:
                    old_key = recent_key
                    old_kind = 1
                else:
                    old_key = frequent_key
                    old_kind = 2
            if old_kind == 1:
                old_size = self.ghost_recent.pop(old_key)
                self.ghost_recent_bytes -= old_size
            else:
                old_size = self.ghost_frequent.pop(old_key)
                self.ghost_frequent_bytes -= old_size
            self.ghost_bytes -= old_size

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        if kind == 1:
            base = max(1, self.ghost_recent_bytes)
            delta = self.ghost_frequent_bytes // base or 1
            self.recent_target = min(self.capacity, self.recent_target + min(self.capacity, delta))
        else:
            base = max(1, self.ghost_frequent_bytes)
            delta = self.ghost_recent_bytes // base or 1
            self.recent_target = max(0, self.recent_target - min(self.capacity, delta))

    def _remove_resident(self, key):
        size = self.recent.pop(key, None)
        if size is not None:
            self.recent_bytes -= size
            self.used -= size
            return size, 1
        size = self.frequent.pop(key, None)
        if size is not None:
            self.frequent_bytes -= size
            self.used -= size
            return size, 2
        return 0, 0

    def _evict_one(self):
        if self.recent and (not self.frequent or self.recent_bytes > self.recent_target):
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 1)
            return key
        if self.frequent:
            key, size = self.frequent.popitem(last=False)
            self.frequent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 2)
            return key
        if self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 1)
            return key
        return None

    def _make_room(self, incoming):
        evicted = []
        while self.used + incoming > self.capacity:
            key = self._evict_one()
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))
        _ = now

        if key in self.recent:
            old_size = self.recent.pop(key)
            self.recent_bytes -= old_size
            self.used -= old_size
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size)
            self.frequent[key] = size
            self.frequent_bytes += size
            self.used += size
            return evicted

        if key in self.frequent:
            old_size = self.frequent.pop(key)
            self.frequent_bytes -= old_size
            self.used -= old_size
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size)
            self.frequent[key] = size
            self.frequent_bytes += size
            self.used += size
            return evicted

        if size <= 0 or size > self.capacity:
            return []

        if key in self.ghost_recent:
            self._adjust_target(1)
            ghost_kind = 1
            self._forget_ghost(key)
        elif key in self.ghost_frequent:
            self._adjust_target(2)
            ghost_kind = 2
            self._forget_ghost(key)
        else:
            ghost_kind = 0

        evicted = self._make_room(size)
        if ghost_kind:
            self.frequent[key] = size
            self.frequent_bytes += size
        else:
            self.recent[key] = size
            self.recent_bytes += size
        self.used += size
        return evicted
