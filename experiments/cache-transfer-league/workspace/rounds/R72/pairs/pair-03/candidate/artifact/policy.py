from collections import OrderedDict


class Policy:
    """Byte-aware adaptive recency/frequency cache with bounded ghost history."""

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
        self._ghost_recent_bytes = 0
        self._ghost_frequent_bytes = 0
        self._ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self._ghost_count_limit = 4096

    def _drop_ghost(self, key):
        value = self.ghost_recent.pop(key, None)
        if value is not None:
            self._ghost_recent_bytes -= value[0]
            return
        value = self.ghost_frequent.pop(key, None)
        if value is not None:
            self._ghost_frequent_bytes -= value[0]

    def _remember_ghost(self, key, size, kind):
        self._drop_ghost(key)
        self._ghost_serial += 1
        value = (max(0, int(size)), self._ghost_serial)
        if kind == 1:
            self.ghost_recent[key] = value
            self._ghost_recent_bytes += value[0]
        else:
            self.ghost_frequent[key] = value
            self._ghost_frequent_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self._ghost_recent_bytes + self._ghost_frequent_bytes > self._ghost_limit or
               len(self.ghost_recent) + len(self.ghost_frequent) > self._ghost_count_limit):
            recent_serial = None
            frequent_serial = None
            if self.ghost_recent:
                recent_serial = next(iter(self.ghost_recent.values()))[1]
            if self.ghost_frequent:
                frequent_serial = next(iter(self.ghost_frequent.values()))[1]
            if frequent_serial is None or (recent_serial is not None and recent_serial < frequent_serial):
                _, value = self.ghost_recent.popitem(last=False)
                self._ghost_recent_bytes -= value[0]
            else:
                _, value = self.ghost_frequent.popitem(last=False)
                self._ghost_frequent_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        if kind == 1:
            if self._ghost_recent_bytes == 0:
                delta = self.capacity
            else:
                delta = max(1, min(self.capacity, self._ghost_frequent_bytes // self._ghost_recent_bytes or 1))
            self.recent_target = min(self.capacity, self.recent_target + delta)
        else:
            if self._ghost_frequent_bytes == 0:
                delta = self.capacity
            else:
                delta = max(1, min(self.capacity, self._ghost_recent_bytes // self._ghost_frequent_bytes or 1))
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
        del now
        key = int(key)
        size = max(0, int(size))

        if key in self.recent or key in self.frequent:
            _, kind = self._remove_resident(key)
            if size > self.capacity:
                self._remember_ghost(key, size, kind)
                return [key]
            self._drop_ghost(key)
            evicted = self._make_room(size)
            self.frequent[key] = size
            self.frequent_bytes += size
            self.used += size
            return evicted

        ghost_kind = 0
        if key in self.ghost_recent:
            ghost_kind = 1
        elif key in self.ghost_frequent:
            ghost_kind = 2

        if size > self.capacity:
            return []

        if ghost_kind:
            self._adjust_target(ghost_kind)
            self._drop_ghost(key)

        evicted = self._make_room(size)
        if ghost_kind:
            self.frequent[key] = size
            self.frequent_bytes += size
        else:
            self.recent[key] = size
            self.recent_bytes += size
        self.used += size
        return evicted
