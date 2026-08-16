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
            if self.ghost_recent and self.ghost_frequent:
                recent_serial = next(iter(self.ghost_recent.values()))[1]
                frequent_serial = next(iter(self.ghost_frequent.values()))[1]
                ghosts = self.ghost_recent if recent_serial <= frequent_serial else self.ghost_frequent
            elif self.ghost_recent:
                ghosts = self.ghost_recent
            elif self.ghost_frequent:
                ghosts = self.ghost_frequent
            else:
                break
            _, value = ghosts.popitem(last=False)
            self._ghost_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        if kind == 1:
            first = self.ghost_recent_bytes if hasattr(self, 'ghost_recent_bytes') else sum(v[0] for v in self.ghost_recent.values())
            second = self.ghost_frequent_bytes if hasattr(self, 'ghost_frequent_bytes') else sum(v[0] for v in self.ghost_frequent.values())
            delta = self.capacity if second == 0 else max(1, min(self.capacity, second // max(1, first)))
            self.recent_target = min(self.capacity, self.recent_target + delta)
        else:
            first = self.ghost_recent_bytes if hasattr(self, 'ghost_recent_bytes') else sum(v[0] for v in self.ghost_recent.values())
            second = self.ghost_frequent_bytes if hasattr(self, 'ghost_frequent_bytes') else sum(v[0] for v in self.ghost_frequent.values())
            delta = self.capacity if first == 0 else max(1, min(self.capacity, first // max(1, second)))
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
        if self.recent and (not self.frequent or (self.recent_target > 0 and self.recent_bytes >= self.recent_target)):
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
            if size > self.capacity:
                self._drop_ghost(key)
                return [key]
            evicted = self._make_room(size)
            self._drop_ghost(key)
            self.frequent[key] = size
            self.frequent_bytes += size
            self.used += size
            return evicted

        if size > self.capacity:
            return []

        if key in self.ghost_recent:
            self._adjust_target(1)
            self._drop_ghost(key)
            evicted = self._make_room(size)
            self.frequent[key] = size
            self.frequent_bytes += size
        elif key in self.ghost_frequent:
            self._adjust_target(2)
            self._drop_ghost(key)
            evicted = self._make_room(size)
            self.frequent[key] = size
            self.frequent_bytes += size
        else:
            evicted = self._make_room(size)
            self.recent[key] = size
            self.recent_bytes += size

        self.used += size
        return evicted
