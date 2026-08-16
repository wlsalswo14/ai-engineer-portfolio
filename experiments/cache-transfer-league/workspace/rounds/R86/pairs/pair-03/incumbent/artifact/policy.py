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
        value = (max(1, int(size)), self.serial)
        if kind == 1:
            self.ghost_recent[key] = value
        else:
            self.ghost_frequent[key] = value
        self.ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_recent) + len(self.ghost_frequent) > self.ghost_count_limit):
            source = self.ghost_recent
            if not source or (self.ghost_frequent and
                              next(iter(self.ghost_frequent.values()))[1] <
                              next(iter(source.values()))[1]):
                source = self.ghost_frequent
            _, value = source.popitem(last=False)
            self.ghost_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        b1 = sum(value[0] for value in self.ghost_recent.values())
        b2 = sum(value[0] for value in self.ghost_frequent.values())
        if kind == 1:
            delta = self.capacity if b1 == 0 else max(1, min(self.capacity, b2 // b1 or 1))
            self.target = min(self.capacity, self.target + delta)
        else:
            delta = self.capacity if b2 == 0 else max(1, min(self.capacity, b1 // b2 or 1))
            self.target = max(0, self.target - delta)

    def _take_resident(self, key):
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
        return None

    def _prefer_recent(self, ghost_kind):
        if not self.recent:
            return False
        if not self.frequent:
            return True
        if ghost_kind == 1:
            return self.recent_bytes > self.target or (
                self.recent_bytes == self.target and bool(self.ghost_frequent)
            )
        if ghost_kind == 2:
            return self.recent_bytes >= self.target
        return self.recent_bytes > self.target

    def _evict_one(self, ghost_kind):
        if self._prefer_recent(ghost_kind) and self.recent:
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

    def _make_room(self, incoming, ghost_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            key = self._evict_one(ghost_kind)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key, size, now):
        key = int(key)
        size = max(0, int(size))
        resident = self._take_resident(key)

        if resident is not None:
            old_size, old_kind = resident
            if size <= 0 or size > self.capacity:
                self._remember_ghost(key, old_size, old_kind)
                return [key]
            evicted = self._make_room(size, 0)
            if self.used + size > self.capacity:
                self._remember_ghost(key, old_size, old_kind)
                return evicted + [key]
            self._drop_ghost(key)
            self.frequent[key] = size
            self.frequent_bytes += size
            self.used += size
            return evicted

        if size <= 0 or size > self.capacity:
            return []

        ghost_kind = 1 if key in self.ghost_recent else 2 if key in self.ghost_frequent else 0
        if ghost_kind:
            self._adjust_target(ghost_kind)
            self._drop_ghost(key)

        evicted = self._make_room(size, ghost_kind)
        if self.used + size > self.capacity:
            return evicted

        if ghost_kind:
            self.frequent[key] = size
            self.frequent_bytes += size
        else:
            self.recent[key] = size
            self.recent_bytes += size
        self.used += size
        return evicted
