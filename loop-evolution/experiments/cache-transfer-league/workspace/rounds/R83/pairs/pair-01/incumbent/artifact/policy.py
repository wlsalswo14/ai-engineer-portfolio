from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.recent_bytes = 0
        self.protected_bytes = 0
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
        value = self.ghost_protected.pop(key, None)
        if value is not None:
            self._ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, protected):
        self._drop_ghost(key)
        self._serial += 1
        value = (size, self._serial)
        if protected:
            self.ghost_protected[key] = value
        else:
            self.ghost_recent[key] = value
        self._ghost_bytes += size
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self._ghost_bytes > self._ghost_limit or
               len(self.ghost_recent) + len(self.ghost_protected) > self._ghost_count_limit):
            source = None
            if self.ghost_recent:
                source = self.ghost_recent
                serial = next(iter(source.values()))[1]
            else:
                serial = None
            if self.ghost_protected:
                other_serial = next(iter(self.ghost_protected.values()))[1]
                if serial is None or other_serial < serial:
                    source = self.ghost_protected
            if source is None:
                break
            _, value = source.popitem(last=False)
            self._ghost_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        recent_ghost_bytes = sum(value[0] for value in self.ghost_recent.values())
        protected_ghost_bytes = sum(value[0] for value in self.ghost_protected.values())
        if kind == 1:
            delta = self.capacity if recent_ghost_bytes == 0 else max(1, protected_ghost_bytes // recent_ghost_bytes)
            self.recent_target = min(self.capacity, self.recent_target + min(self.capacity, delta))
        else:
            delta = self.capacity if protected_ghost_bytes == 0 else max(1, recent_ghost_bytes // protected_ghost_bytes)
            self.recent_target = max(0, self.recent_target - min(self.capacity, delta))

    def _remove_resident(self, key):
        size = self.recent.pop(key, None)
        if size is not None:
            self.recent_bytes -= size
            self.used -= size
            return size, 1
        size = self.protected.pop(key, None)
        if size is not None:
            self.protected_bytes -= size
            self.used -= size
            return size, 2
        return 0, 0

    def _evict_one(self):
        if self.recent and (self.recent_bytes > self.recent_target or not self.protected):
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, False)
            return key
        if self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
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

        if key in self.recent or key in self.protected:
            self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size)
            self._drop_ghost(key)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            return evicted

        if size <= 0 or size > self.capacity:
            return []

        if key in self.ghost_recent:
            self._adjust_target(1)
            self._drop_ghost(key)
            evicted = self._make_room(size)
            self.protected[key] = size
            self.protected_bytes += size
        elif key in self.ghost_protected:
            self._adjust_target(2)
            self._drop_ghost(key)
            evicted = self._make_room(size)
            self.protected[key] = size
            self.protected_bytes += size
        else:
            evicted = self._make_room(size)
            self.recent[key] = size
            self.recent_bytes += size

        self.used += size
        return evicted
