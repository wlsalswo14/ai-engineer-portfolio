from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.used = 0
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.ghost_bytes = 0
        self.recent_target = self.capacity // 2
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096

    def _drop_ghost(self, key):
        value = self.ghost_recent.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value
        value = self.ghost_frequent.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value

    def _remember_ghost(self, key, size, kind):
        self._drop_ghost(key)
        if kind == 1:
            self.ghost_recent[key] = size
        else:
            self.ghost_frequent[key] = size
        self.ghost_bytes += size
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_recent) + len(self.ghost_frequent) > self.ghost_count_limit):
            candidate_kind = 1
            if self.ghost_recent:
                candidate_key = next(iter(self.ghost_recent))
                candidate_size = self.ghost_recent[candidate_key]
            else:
                candidate_kind = 2
                candidate_key = next(iter(self.ghost_frequent))
                candidate_size = self.ghost_frequent[candidate_key]
            if self.ghost_frequent:
                frequent_key = next(iter(self.ghost_frequent))
                if (candidate_kind == 1 and
                        self.ghost_frequent[frequent_key] < candidate_size):
                    candidate_kind = 2
                    candidate_key = frequent_key
                    candidate_size = self.ghost_frequent[frequent_key]
            if candidate_kind == 1:
                self.ghost_recent.pop(candidate_key)
            else:
                self.ghost_frequent.pop(candidate_key)
            self.ghost_bytes -= candidate_size

    def _adjust_target(self, kind):
        if self.capacity == 0:
            return
        if kind == 1:
            if self.ghost_recent:
                delta = max(1, min(self.capacity,
                                   len(self.ghost_frequent) // len(self.ghost_recent) or 1))
            else:
                delta = self.capacity
            self.recent_target = min(self.capacity, self.recent_target + delta)
        else:
            if self.ghost_frequent:
                delta = max(1, min(self.capacity,
                                   len(self.ghost_recent) // len(self.ghost_frequent) or 1))
            else:
                delta = self.capacity
            self.recent_target = max(0, self.recent_target - delta)

    def _remove_resident(self, key):
        value = self.recent.pop(key, None)
        if value is not None:
            self.recent_bytes -= value
            self.used -= value
            return value, 1
        value = self.frequent.pop(key, None)
        if value is not None:
            self.frequent_bytes -= value
            self.used -= value
            return value, 2
        return 0, 0

    def _evict_one(self):
        if self.recent and (self.recent_bytes > self.recent_target or not self.frequent):
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

        if key in self.recent or key in self.frequent:
            self._remove_resident(key)
            if size == 0 or size > self.capacity:
                self._drop_ghost(key)
                return [key]
            evicted = self._make_room(size)
            self._drop_ghost(key)
            self.frequent[key] = size
            self.frequent_bytes += size
            self.used += size
            return evicted

        if size == 0 or size > self.capacity:
            return []

        if key in self.ghost_recent:
            kind = 1
        elif key in self.ghost_frequent:
            kind = 2
        else:
            kind = 0

        if kind:
            self._adjust_target(kind)
            self._drop_ghost(key)

        evicted = self._make_room(size)
        if kind:
            self.frequent[key] = size
            self.frequent_bytes += size
        else:
            self.recent[key] = size
            self.recent_bytes += size
        self.used += size
        return evicted
