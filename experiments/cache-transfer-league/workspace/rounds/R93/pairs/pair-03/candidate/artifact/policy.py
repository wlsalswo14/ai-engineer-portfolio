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
        self.serial = 0

    def _drop_ghost(self, key):
        self.ghost_recent.pop(key, None)
        self.ghost_frequent.pop(key, None)

    def _remember_ghost(self, key, size, kind):
        self._drop_ghost(key)
        self.serial += 1
        value = (max(1, int(size)), self.serial)
        if kind == 1:
            self.ghost_recent[key] = value
        else:
            self.ghost_frequent[key] = value
        while len(self.ghost_recent) + len(self.ghost_frequent) > 4096:
            source = self.ghost_recent if self.ghost_recent else self.ghost_frequent
            source.popitem(last=False)

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        recent_bytes = sum(value[0] for value in self.ghost_recent.values())
        frequent_bytes = sum(value[0] for value in self.ghost_frequent.values())
        if kind == 1:
            delta = self.capacity if recent_bytes == 0 else max(1, min(self.capacity, frequent_bytes // recent_bytes or 1))
            self.target = min(self.capacity, self.target + delta)
        else:
            delta = self.capacity if frequent_bytes == 0 else max(1, min(self.capacity, recent_bytes // frequent_bytes or 1))
            self.target = max(0, self.target - delta)

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

    def _evict_one(self, mode):
        choose_recent = False
        if mode == 1 and self.recent and self.recent_bytes >= self.target:
            choose_recent = True
        elif mode == 2 and self.recent and self.recent_bytes <= self.target:
            choose_recent = False
        elif self.recent and self.recent_bytes > self.target:
            choose_recent = True
        elif self.recent and not self.frequent:
            choose_recent = True

        if choose_recent and self.recent:
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

    def _make_room(self, incoming, mode):
        evicted = []
        while self.used + incoming > self.capacity:
            key = self._evict_one(mode)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key, size, now):
        key = int(key)
        size = int(size)

        if key in self.recent or key in self.frequent:
            self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            if self.used + size > self.capacity:
                return evicted + [key]
            self.frequent[key] = size
            self.frequent_bytes += size
            self.used += size
            return evicted

        mode = 1 if key in self.ghost_recent else 2 if key in self.ghost_frequent else 0
        if size <= 0 or size > self.capacity:
            return []

        if mode:
            self._adjust_target(mode)
            self._drop_ghost(key)

        evicted = self._make_room(size, mode)
        if self.used + size > self.capacity:
            return evicted

        if mode:
            self.frequent[key] = size
            self.frequent_bytes += size
        else:
            self.recent[key] = size
            self.recent_bytes += size
        self.used += size
        return evicted
