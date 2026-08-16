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
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096
        self.ghost_bytes = 0
        self.serial = 0

    def _discard_ghost(self, key):
        value = self.ghost_recent.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]
        value = self.ghost_frequent.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, frequent):
        self._discard_ghost(key)
        self.serial += 1
        value = (max(1, int(size)), self.serial)
        if frequent:
            self.ghost_frequent[key] = value
        else:
            self.ghost_recent[key] = value
        self.ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_recent) + len(self.ghost_frequent) > self.ghost_count_limit):
            source = None
            oldest = None
            for ghosts in (self.ghost_recent, self.ghost_frequent):
                if ghosts:
                    value = next(iter(ghosts.values()))
                    if oldest is None or value[1] < oldest[1]:
                        source = ghosts
                        oldest = value
            _, value = source.popitem(last=False)
            self.ghost_bytes -= value[0]

    def _adapt(self, frequent_ghost):
        if self.capacity <= 0:
            return
        recent_bytes = sum(value[0] for value in self.ghost_recent.values())
        frequent_bytes = sum(value[0] for value in self.ghost_frequent.values())
        if frequent_ghost:
            delta = (self.capacity if frequent_bytes == 0 else
                     max(1, min(self.capacity, recent_bytes // frequent_bytes or 1)))
            self.target = max(0, self.target - delta)
        else:
            delta = (self.capacity if recent_bytes == 0 else
                     max(1, min(self.capacity, frequent_bytes // recent_bytes or 1)))
            self.target = min(self.capacity, self.target + delta)

    def _remove(self, key):
        size = self.recent.pop(key, None)
        if size is not None:
            self.recent_bytes -= size
            self.used -= size
            return size, False
        size = self.frequent.pop(key, None)
        if size is not None:
            self.frequent_bytes -= size
            self.used -= size
            return size, True
        return None

    def _evict_one(self, prefer_recent):
        if prefer_recent and self.recent:
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
            key = self._evict_one(self.recent_bytes > self.target)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key, size, now):
        key = int(key)
        size = max(0, int(size))
        resident = key in self.recent or key in self.frequent

        if size <= 0 or size > self.capacity:
            if resident:
                self._remove(key)
                return [key]
            return []

        if resident:
            self._remove(key)
            evicted = self._make_room(size)
            if self.used + size > self.capacity:
                return evicted + [key]
            self._discard_ghost(key)
            self.frequent[key] = size
            self.frequent_bytes += size
            self.used += size
            return evicted

        in_recent_ghost = key in self.ghost_recent
        in_frequent_ghost = key in self.ghost_frequent
        if in_recent_ghost or in_frequent_ghost:
            self._adapt(in_frequent_ghost)
            self._discard_ghost(key)

        evicted = self._make_room(size)
        if self.used + size > self.capacity:
            return evicted

        if in_recent_ghost or in_frequent_ghost:
            self.frequent[key] = size
            self.frequent_bytes += size
        else:
            self.recent[key] = size
            self.recent_bytes += size
        self.used += size
        return evicted
