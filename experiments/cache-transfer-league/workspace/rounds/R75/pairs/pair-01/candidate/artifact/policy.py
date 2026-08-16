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
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096

    def _remove_ghost(self, key):
        value = self.ghost_recent.pop(key, None)
        if value is not None:
            self.ghost_recent_bytes -= value
        value = self.ghost_frequent.pop(key, None)
        if value is not None:
            self.ghost_frequent_bytes -= value

    def _trim_ghosts(self):
        while (self.ghost_recent_bytes + self.ghost_frequent_bytes > self.ghost_limit or
               len(self.ghost_recent) + len(self.ghost_frequent) > self.ghost_count_limit):
            if self.ghost_recent and self.ghost_frequent:
                target = (self.ghost_recent if next(iter(self.ghost_recent.values()))[1] <=
                          next(iter(self.ghost_frequent.values()))[1] else self.ghost_frequent)
            elif self.ghost_recent:
                target = self.ghost_recent
            else:
                target = self.ghost_frequent
            key, value = target.popitem(last=False)
            if target is self.ghost_recent:
                self.ghost_recent_bytes -= value[0]
            else:
                self.ghost_frequent_bytes -= value[0]

    def _remember_ghost(self, key, size, frequent):
        self._remove_ghost(key)
        serial = getattr(self, "_serial", 0) + 1
        self._serial = serial
        value = (max(0, int(size)), serial)
        target = self.ghost_frequent if frequent else self.ghost_recent
        target[key] = value
        if frequent:
            self.ghost_frequent_bytes += value[0]
        else:
            self.ghost_recent_bytes += value[0]
        self._trim_ghosts()

    def _adjust_target(self, frequent_ghost):
        if self.capacity <= 0:
            return
        recent = self.ghost_recent_bytes
        frequent = self.ghost_frequent_bytes
        if frequent_ghost:
            delta = self.capacity if recent == 0 else max(1, min(self.capacity, frequent // recent or 1))
            self.recent_target = max(0, self.recent_target - delta)
        else:
            delta = self.capacity if frequent == 0 else max(1, min(self.capacity, recent // frequent or 1))
            self.recent_target = min(self.capacity, self.recent_target + delta)

    def _remove_resident(self, key):
        value = self.recent.pop(key, None)
        if value is not None:
            self.recent_bytes -= value
            self.used -= value
            return value, False
        value = self.frequent.pop(key, None)
        if value is not None:
            self.frequent_bytes -= value
            self.used -= value
            return value, True
        return None, False

    def _evict_one(self):
        if self.recent and (not self.frequent or self.recent_bytes > self.recent_target):
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, False)
            return key
        if self.frequent:
            key, size = self.frequent.popitem(last=False)
            self.frequent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, True)
            return key
        if self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, False)
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
        resident = key in self.recent or key in self.frequent

        if size > self.capacity:
            if resident:
                self._remove_resident(key)
                return [key]
            return []

        if resident:
            _, _ = self._remove_resident(key)
            self._remove_ghost(key)
            evicted = self._make_room(size)
            self.frequent[key] = size
            self.frequent_bytes += size
            self.used += size
            return evicted

        in_recent_ghost = key in self.ghost_recent
        in_frequent_ghost = key in self.ghost_frequent
        if in_recent_ghost or in_frequent_ghost:
            self._adjust_target(in_frequent_ghost)
            self._remove_ghost(key)
            evicted = self._make_room(size)
            self.frequent[key] = size
            self.frequent_bytes += size
        else:
            evicted = self._make_room(size)
            self.recent[key] = size
            self.recent_bytes += size
        self.used += size
        return evicted
