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
            oldest = None
            source = None
            for ghosts in (self.ghost_recent, self.ghost_frequent):
                if ghosts:
                    key = next(iter(ghosts))
                    value = ghosts[key]
                    if oldest is None or value[1] < oldest[1]:
                        oldest = value
                        source = ghosts
            key, value = source.popitem(last=False)
            self.ghost_bytes -= value[0]

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

    def _make_room(self, incoming, ghost_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            prefer_recent = self.recent_bytes > self.target
            if ghost_kind == 1 and self.recent_bytes >= self.target:
                prefer_recent = True
            elif ghost_kind == 2 and self.recent_bytes == self.target:
                prefer_recent = False
            key = self._evict_one(prefer_recent)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key, size, now):
        key = int(key)
        size = max(0, int(size))

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

        ghost_kind = 1 if key in self.ghost_recent else 2 if key in self.ghost_frequent else 0
        if size <= 0 or size > self.capacity:
            return []
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
