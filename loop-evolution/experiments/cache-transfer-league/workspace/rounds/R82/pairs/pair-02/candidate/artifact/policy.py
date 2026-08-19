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
        self._serial = 0
        self._ghost_bytes = 0
        self._ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self._ghost_count_limit = 4096

    def _drop_ghost(self, key):
        value = self.ghost_recent.pop(key, None)
        if value is not None:
            self.ghost_recent_bytes -= value[0]
            self._ghost_bytes -= value[0]
        value = self.ghost_frequent.pop(key, None)
        if value is not None:
            self.ghost_frequent_bytes -= value[0]
            self._ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, kind):
        self._drop_ghost(key)
        self._serial += 1
        value = (max(1, int(size)), self._serial)
        if kind == 1:
            self.ghost_recent[key] = value
            self.ghost_recent_bytes += value[0]
        else:
            self.ghost_frequent[key] = value
            self.ghost_frequent_bytes += value[0]
        self._ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self._ghost_bytes > self._ghost_limit or
               len(self.ghost_recent) + len(self.ghost_frequent) > self._ghost_count_limit):
            kind = 1
            serial = None
            if self.ghost_recent:
                serial = next(iter(self.ghost_recent.values()))[1]
            if self.ghost_frequent:
                other = next(iter(self.ghost_frequent.values()))[1]
                if serial is None or other < serial:
                    kind = 2
            ghosts = self.ghost_recent if kind == 1 else self.ghost_frequent
            _, value = ghosts.popitem(last=False)
            if kind == 1:
                self.ghost_recent_bytes -= value[0]
            else:
                self.ghost_frequent_bytes -= value[0]
            self._ghost_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        if kind == 1:
            first = self.ghost_recent_bytes
            second = self.ghost_frequent_bytes
            delta = self.capacity if first == 0 else max(1, min(self.capacity, second // first or 1))
            self.recent_target = min(self.capacity, self.recent_target + delta)
        else:
            first = self.ghost_recent_bytes
            second = self.ghost_frequent_bytes
            delta = self.capacity if second == 0 else max(1, min(self.capacity, first // second or 1))
            self.recent_target = max(0, self.recent_target - delta)

    def _remove_resident(self, key):
        value = self.recent.pop(key, None)
        if value is not None:
            self.recent_bytes -= value[0]
            self.used -= value[0]
            return value[0], 1
        value = self.frequent.pop(key, None)
        if value is not None:
            self.frequent_bytes -= value[0]
            self.used -= value[0]
            return value[0], 2
        return 0, 0

    def _evict_one(self, prefer_recent):
        if prefer_recent and self.recent:
            key, value = self.recent.popitem(last=False)
            size = value[0]
            self.recent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 1)
            return key
        if self.frequent:
            key, value = self.frequent.popitem(last=False)
            size = value[0]
            self.frequent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 2)
            return key
        if self.recent:
            key, value = self.recent.popitem(last=False)
            size = value[0]
            self.recent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 1)
            return key
        return None

    def _make_room(self, incoming, ghost_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            prefer_recent = self.recent_bytes > self.recent_target
            if ghost_kind == 1 and self.recent_bytes >= self.recent_target:
                prefer_recent = True
            elif ghost_kind == 2 and self.recent_bytes == self.recent_target:
                prefer_recent = True
            key = self._evict_one(prefer_recent)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))
        self._serial += 1

        if self.capacity <= 0:
            return []

        if key in self.recent or key in self.frequent:
            _, kind = self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            self._drop_ghost(key)
            self.frequent[key] = (size, self._serial)
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
        if ghost_kind:
            self.frequent[key] = (size, self._serial)
            self.frequent_bytes += size
        else:
            self.recent[key] = (size, self._serial)
            self.recent_bytes += size
        self.used += size
        return evicted
