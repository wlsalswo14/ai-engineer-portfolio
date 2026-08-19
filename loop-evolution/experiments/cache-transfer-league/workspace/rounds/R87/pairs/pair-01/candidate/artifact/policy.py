from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        self.capacity = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.used = 0
        self.target = self.capacity // 2
        self.ghost_bytes = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096
        self.serial = 0

    def _drop_ghost(self, key):
        value = self.ghost_recent.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]
        value = self.ghost_frequent.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, kind):
        self._drop_ghost(key)
        self.serial += 1
        value = (size, self.serial)
        if kind == 1:
            self.ghost_recent[key] = value
        else:
            self.ghost_frequent[key] = value
        self.ghost_bytes += size
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_recent) + len(self.ghost_frequent) > self.ghost_count_limit):
            if not self.ghost_recent:
                source = self.ghost_frequent
            elif not self.ghost_frequent:
                source = self.ghost_recent
            elif next(iter(self.ghost_recent.values()))[1] <= next(iter(self.ghost_frequent.values()))[1]:
                source = self.ghost_recent
            else:
                source = self.ghost_frequent
            _, value = source.popitem(last=False)
            self.ghost_bytes -= value[0]

    def _remove_resident(self, key):
        value = self.recent.pop(key, None)
        if value is not None:
            self.recent_bytes -= value
            self.used -= value
            return value
        value = self.frequent.pop(key, None)
        if value is not None:
            self.frequent_bytes -= value
            self.used -= value
            return value
        return None

    def _adapt(self, kind, size):
        if self.capacity <= 0:
            return
        if kind == 1:
            delta = max(1, min(self.capacity, max(size, self.capacity // max(1, len(self.ghost_recent)))))
            self.target = min(self.capacity, self.target + delta)
        else:
            delta = max(1, min(self.capacity, max(size, self.capacity // max(1, len(self.ghost_frequent)))))
            self.target = max(0, self.target - delta)

    def _evict_one(self, prefer_recent):
        if self.recent and (self.recent_bytes > self.target or
                            (prefer_recent and self.recent_bytes == self.target)):
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

    def _make_room(self, incoming, from_frequent_ghost=False):
        evicted = []
        while self.used + incoming > self.capacity:
            key = self._evict_one(from_frequent_ghost)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key, size, now):
        key = int(key)
        size = max(0, int(size))

        if key in self.recent or key in self.frequent:
            self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size)
            if self.used + size > self.capacity:
                return evicted + [key]
            self._drop_ghost(key)
            self.frequent[key] = size
            self.frequent_bytes += size
            self.used += size
            return evicted

        ghost_kind = 0
        if key in self.ghost_recent:
            ghost_kind = 1
        elif key in self.ghost_frequent:
            ghost_kind = 2

        if size <= 0 or size > self.capacity:
            if ghost_kind:
                self._drop_ghost(key)
            return []

        if ghost_kind:
            self._adapt(ghost_kind, size)
            self._drop_ghost(key)

        evicted = self._make_room(size, ghost_kind == 2)
        if self.used + size > self.capacity:
            return evicted

        self.recent[key] = size
        self.recent_bytes += size
        self.used += size
        return evicted
