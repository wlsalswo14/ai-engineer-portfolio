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
        self.ghost_bytes = 0
        self.used = 0
        self.target_recent = self.capacity // 2
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

    def _remember_ghost(self, key, size, frequent):
        self._drop_ghost(key)
        self.serial += 1
        value = (size, self.serial)
        if frequent:
            self.ghost_frequent[key] = value
        else:
            self.ghost_recent[key] = value
        self.ghost_bytes += size
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_recent) + len(self.ghost_frequent) > self.ghost_count_limit):
            if self.ghost_recent and self.ghost_frequent:
                rk = next(iter(self.ghost_recent))
                fk = next(iter(self.ghost_frequent))
                source = (self.ghost_recent if
                          self.ghost_recent[rk][1] <= self.ghost_frequent[fk][1]
                          else self.ghost_frequent)
            elif self.ghost_recent:
                source = self.ghost_recent
            else:
                source = self.ghost_frequent
            _, value = source.popitem(last=False)
            self.ghost_bytes -= value[0]

    def _ghost_sum(self, table):
        return sum(value[0] for value in table.values())

    def _adapt(self, kind):
        if self.capacity <= 0:
            return
        if kind == 1:
            left = self._ghost_sum(self.ghost_recent)
            right = self._ghost_sum(self.ghost_frequent)
            delta = max(1, min(self.capacity, right // max(1, left)))
            self.target_recent = min(self.capacity, self.target_recent + delta)
        elif kind == 2:
            left = self._ghost_sum(self.ghost_recent)
            right = self._ghost_sum(self.ghost_frequent)
            delta = max(1, min(self.capacity, left // max(1, right)))
            self.target_recent = max(0, self.target_recent - delta)

    def _evict_recent(self):
        key, value = self.recent.popitem(last=False)
        size = value[0]
        self.recent_bytes -= size
        self.used -= size
        self._remember_ghost(key, size, False)
        return key

    def _evict_frequent(self):
        key, value = self.frequent.popitem(last=False)
        size = value[0]
        self.frequent_bytes -= size
        self.used -= size
        self._remember_ghost(key, size, True)
        return key

    def _make_room(self, incoming, ghost_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            prefer_recent = (self.recent_bytes > self.target_recent or
                              (ghost_kind == 2 and
                               self.recent_bytes == self.target_recent))
            if prefer_recent and self.recent:
                evicted.append(self._evict_recent())
            elif self.frequent:
                evicted.append(self._evict_frequent())
            elif self.recent:
                evicted.append(self._evict_recent())
            else:
                break
        return evicted

    def _store_recent(self, key, size):
        self.recent[key] = (size, 1)
        self.recent_bytes += size
        self.used += size

    def _store_frequent(self, key, size, frequency):
        self.frequent[key] = (size, frequency)
        self.frequent_bytes += size
        self.used += size

    def access(self, key, size, now):
        key = int(key)
        size = int(size)

        value = self.recent.pop(key, None)
        if value is not None:
            old_size = value[0]
            self.recent_bytes -= old_size
            self.used -= old_size
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            if self.used + size > self.capacity:
                return evicted + [key]
            self._store_frequent(key, size, 2)
            return evicted

        value = self.frequent.pop(key, None)
        if value is not None:
            old_size, frequency = value
            self.frequent_bytes -= old_size
            self.used -= old_size
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            if self.used + size > self.capacity:
                return evicted + [key]
            self._store_frequent(key, size, min(frequency + 1, 1 << 30))
            return evicted

        if key in self.ghost_recent:
            ghost_kind = 1
        elif key in self.ghost_frequent:
            ghost_kind = 2
        else:
            ghost_kind = 0

        if size <= 0 or size > self.capacity:
            if ghost_kind:
                self._drop_ghost(key)
            return []

        if ghost_kind:
            self._adapt(ghost_kind)
            self._drop_ghost(key)
            evicted = self._make_room(size, ghost_kind)
            if self.used + size > self.capacity:
                return evicted
            self._store_frequent(key, size, 2)
            return evicted

        evicted = self._make_room(size, 0)
        if self.used + size > self.capacity:
            return evicted
        self._store_recent(key, size)
        return evicted
