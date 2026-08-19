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

    def _drop_ghost(self, key):
        value = self.ghost_recent.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value
        value = self.ghost_frequent.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value

    def _remember_ghost(self, key, size, frequent):
        self._drop_ghost(key)
        value = max(1, int(size))
        if value > self.ghost_limit:
            return
        if frequent:
            self.ghost_frequent[key] = value
        else:
            self.ghost_recent[key] = value
        self.ghost_bytes += value
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_recent) + len(self.ghost_frequent) > self.ghost_count_limit):
            source = None
            if self.ghost_recent and self.ghost_frequent:
                source = (self.ghost_recent if
                          next(iter(self.ghost_recent.values())) <=
                          next(iter(self.ghost_frequent.values())) else
                          self.ghost_frequent)
            elif self.ghost_recent:
                source = self.ghost_recent
            else:
                source = self.ghost_frequent
            _, value = source.popitem(last=False)
            self.ghost_bytes -= value

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        recent = sum(self.ghost_recent.values())
        frequent = sum(self.ghost_frequent.values())
        if kind == 1:
            delta = self.capacity if recent == 0 else max(1, min(self.capacity, frequent // recent or 1))
            self.target = min(self.capacity, self.target + delta)
        else:
            delta = self.capacity if frequent == 0 else max(1, min(self.capacity, recent // frequent or 1))
            self.target = max(0, self.target - delta)

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

    def _evict_one(self, mode):
        choose_recent = bool(self.recent) and (
            not self.frequent or
            self.recent_bytes > self.target or
            (mode == 1 and self.recent_bytes == self.target)
        )
        if choose_recent:
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
            self._drop_ghost(key)
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
