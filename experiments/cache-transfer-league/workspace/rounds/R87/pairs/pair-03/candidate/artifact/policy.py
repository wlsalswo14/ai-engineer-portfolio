from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        self.capacity = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.recent_bytes = 0
        self.protected_bytes = 0
        self.used = 0
        self.target = self.capacity // 2
        self.ghost_bytes = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096
        self.serial = 0

    def _forget_ghost(self, key):
        value = self.ghost_recent.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]
        value = self.ghost_protected.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, segment):
        self._forget_ghost(key)
        self.serial += 1
        value = (max(1, int(size)), self.serial)
        if segment == 1:
            self.ghost_recent[key] = value
        else:
            self.ghost_protected[key] = value
        self.ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_recent) + len(self.ghost_protected) > self.ghost_count_limit):
            oldest = None
            source = None
            for table in (self.ghost_recent, self.ghost_protected):
                if table:
                    value = next(iter(table.values()))
                    if oldest is None or value[1] < oldest[1]:
                        oldest = value
                        source = table
            if source is None:
                break
            _, value = source.popitem(last=False)
            self.ghost_bytes -= value[0]

    def _remove_resident(self, key):
        value = self.recent.pop(key, None)
        if value is not None:
            self.recent_bytes -= value
            self.used -= value
            return value
        value = self.protected.pop(key, None)
        if value is not None:
            self.protected_bytes -= value
            self.used -= value
            return value
        return None

    def _evict_one(self, prefer_recent):
        tables = ((self.recent, 1), (self.protected, 2)) if prefer_recent else ((self.protected, 2), (self.recent, 1))
        for table, segment in tables:
            if table:
                key, size = table.popitem(last=False)
                if segment == 1:
                    self.recent_bytes -= size
                else:
                    self.protected_bytes -= size
                self.used -= size
                self._remember_ghost(key, size, segment)
                return key
        return None

    def _make_room(self, incoming, hint):
        evicted = []
        while self.used + incoming > self.capacity:
            prefer_recent = bool(self.recent) and (
                not self.protected or self.recent_bytes > self.target)
            if hint == 1 and self.recent:
                prefer_recent = True
            elif hint == 2 and self.protected:
                prefer_recent = False
            key = self._evict_one(prefer_recent)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key, size, now):
        key = int(key)
        size = max(0, int(size))

        if key in self.recent or key in self.protected:
            self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                self._forget_ghost(key)
                return [key]
            evicted = self._make_room(size, 0)
            if self.used + size > self.capacity:
                return evicted + [key]
            self._forget_ghost(key)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            return evicted

        hint = 1 if key in self.ghost_recent else 2 if key in self.ghost_protected else 0
        if size <= 0 or size > self.capacity:
            return []
        if hint:
            self._forget_ghost(key)

        evicted = self._make_room(size, hint)
        if self.used + size > self.capacity:
            return evicted
        self.recent[key] = size
        self.recent_bytes += size
        self.used += size
        return evicted
