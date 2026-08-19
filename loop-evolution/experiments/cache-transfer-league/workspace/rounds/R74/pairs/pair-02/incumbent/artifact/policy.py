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
        self._serial = 0
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

    def _remember_ghost(self, key, size, band):
        self._drop_ghost(key)
        self._serial += 1
        value = (max(1, int(size)), self._serial)
        if band == 1:
            self.ghost_recent[key] = value
        else:
            self.ghost_frequent[key] = value
        self._ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self._ghost_bytes > self._ghost_limit or
               len(self.ghost_recent) + len(self.ghost_frequent) > self._ghost_count_limit):
            band = None
            serial = None
            if self.ghost_recent:
                band = 1
                serial = next(iter(self.ghost_recent.values()))[1]
            if self.ghost_frequent:
                other = next(iter(self.ghost_frequent.values()))[1]
                if serial is None or other < serial:
                    band = 2
            ghosts = self.ghost_recent if band == 1 else self.ghost_frequent
            _, value = ghosts.popitem(last=False)
            self._ghost_bytes -= value[0]

    def _adjust_target(self, band):
        if self.capacity <= 0:
            return
        b1 = sum(value[0] for value in self.ghost_recent.values())
        b2 = sum(value[0] for value in self.ghost_frequent.values())
        if band == 1:
            delta = self.capacity if b1 == 0 else max(1, min(self.capacity, b2 // b1 or 1))
            self.recent_target = min(self.capacity, self.recent_target + delta)
        else:
            delta = self.capacity if b2 == 0 else max(1, min(self.capacity, b1 // b2 or 1))
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

    def _evict_one(self, prefer_recent):
        if prefer_recent and self.recent:
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

    def _make_room(self, incoming, ghost_band):
        evicted = []
        while self.used + incoming > self.capacity:
            prefer_recent = self.recent_bytes > self.recent_target
            if ghost_band == 1 and self.recent_bytes >= self.recent_target:
                prefer_recent = True
            elif ghost_band == 2 and self.recent_bytes <= self.recent_target:
                prefer_recent = False
            key = self._evict_one(prefer_recent)
            if key is None:
                break
            evicted.append(int(key))
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))
        _ = now

        if key in self.recent or key in self.frequent:
            old_size, band = self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            self._drop_ghost(key)
            self.frequent[key] = size
            self.frequent_bytes += size
            self.used += size
            return evicted

        ghost_band = 1 if key in self.ghost_recent else 2 if key in self.ghost_frequent else 0
        if size <= 0 or size > self.capacity:
            return []
        if ghost_band:
            self._adjust_target(ghost_band)
            self._drop_ghost(key)

        evicted = self._make_room(size, ghost_band)
        if ghost_band:
            self.frequent[key] = size
            self.frequent_bytes += size
        else:
            self.recent[key] = size
            self.recent_bytes += size
        self.used += size
        return evicted
