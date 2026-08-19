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
        self.used = 0
        self.recent_target = self.capacity // 2
        self._ghost_serial = 0
        self._ghost_bytes = 0
        self._ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self._ghost_count_limit = 4096

    def _drop_ghost(self, key):
        value = self.ghost_recent.pop(key, None)
        if value is not None:
            self._ghost_bytes -= value[0]
        value = self.ghost_frequent.pop(key, None)
        if value is not None:
            self._ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, kind):
        self._drop_ghost(key)
        self._ghost_serial += 1
        value = (max(1, int(size)), self._ghost_serial)
        if kind == 1:
            self.ghost_recent[key] = value
        else:
            self.ghost_frequent[key] = value
        self._ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self._ghost_bytes > self._ghost_limit or
               len(self.ghost_recent) + len(self.ghost_frequent) > self._ghost_count_limit):
            kind = 0
            serial = None
            if self.ghost_recent:
                kind = 1
                serial = next(iter(self.ghost_recent.values()))[1]
            if self.ghost_frequent:
                other = next(iter(self.ghost_frequent.values()))[1]
                if serial is None or other < serial:
                    kind = 2
            if kind == 0:
                break
            ghosts = self.ghost_recent if kind == 1 else self.ghost_frequent
            _, value = ghosts.popitem(last=False)
            self._ghost_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        recent_bytes = sum(value[0] for value in self.ghost_recent.values())
        frequent_bytes = sum(value[0] for value in self.ghost_frequent.values())
        if kind == 1:
            delta = self.capacity if recent_bytes == 0 else max(
                1, min(self.capacity, frequent_bytes // recent_bytes or 1)
            )
            self.recent_target = min(self.capacity, self.recent_target + delta)
        else:
            delta = self.capacity if frequent_bytes == 0 else max(
                1, min(self.capacity, recent_bytes // frequent_bytes or 1)
            )
            self.recent_target = max(0, self.recent_target - delta)

    def _evict_one(self, prefer, incoming):
        if prefer == 2:
            if self.recent:
                key, value = self.recent.popitem(last=False)
                self.recent_bytes -= value[0]
                self.used -= value[0]
                self._remember_ghost(key, value[0], 1)
                return key
            if self.frequent:
                key, value = self.frequent.popitem(last=False)
                self.frequent_bytes -= value[0]
                self.used -= value[0]
                self._remember_ghost(key, value[0], 2)
                return key
        else:
            if self.recent and (self.recent_bytes + incoming > self.recent_target or not self.frequent):
                key, value = self.recent.popitem(last=False)
                self.recent_bytes -= value[0]
                self.used -= value[0]
                self._remember_ghost(key, value[0], 1)
                return key
            if self.frequent:
                key, value = self.frequent.popitem(last=False)
                self.frequent_bytes -= value[0]
                self.used -= value[0]
                self._remember_ghost(key, value[0], 2)
                return key
            if self.recent:
                key, value = self.recent.popitem(last=False)
                self.recent_bytes -= value[0]
                self.used -= value[0]
                self._remember_ghost(key, value[0], 1)
                return key
        return None

    def _make_room(self, incoming, prefer):
        evicted = []
        while self.used + incoming > self.capacity:
            key = self._evict_one(prefer, incoming)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))
        now = int(now)

        value = self.recent.pop(key, None)
        if value is not None:
            self.recent_bytes -= value[0]
            self.used -= value[0]
            if size <= 0 or size > self.capacity:
                self._drop_ghost(key)
                return [key]
            self._drop_ghost(key)
            evicted = self._make_room(size, 2)
            self.frequent[key] = (size, now, value[2] + 1)
            self.frequent_bytes += size
            self.used += size
            return evicted

        value = self.frequent.pop(key, None)
        if value is not None:
            self.frequent_bytes -= value[0]
            self.used -= value[0]
            if size <= 0 or size > self.capacity:
                self._drop_ghost(key)
                return [key]
            self._drop_ghost(key)
            evicted = self._make_room(size, 2)
            self.frequent[key] = (size, now, value[2] + 1)
            self.frequent_bytes += size
            self.used += size
            return evicted

        ghost_kind = 1 if key in self.ghost_recent else 2 if key in self.ghost_frequent else 0
        if size <= 0 or size > self.capacity:
            return []

        if ghost_kind:
            self._adjust_target(ghost_kind)
            self._drop_ghost(key)
            evicted = self._make_room(size, 2)
            self.frequent[key] = (size, now, 2)
            self.frequent_bytes += size
        else:
            evicted = self._make_room(size, 1)
            self.recent[key] = (size, now, 1)
            self.recent_bytes += size
        self.used += size
        return evicted
