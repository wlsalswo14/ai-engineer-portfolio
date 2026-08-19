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
        self.ghost_recent_bytes = 0
        self.ghost_protected_bytes = 0
        self.used = 0
        self.recent_target = self.capacity // 2
        self._ghost_bytes = 0
        self._serial = 0
        self._ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self._ghost_count_limit = 4096

    def _discard_ghost(self, key):
        value = self.ghost_recent.pop(key, None)
        if value is not None:
            self.ghost_recent_bytes -= value[0]
            self._ghost_bytes -= value[0]
        value = self.ghost_protected.pop(key, None)
        if value is not None:
            self.ghost_protected_bytes -= value[0]
            self._ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, kind):
        self._discard_ghost(key)
        self._serial += 1
        value = (max(1, int(size)), self._serial)
        if kind == 1:
            self.ghost_recent[key] = value
            self.ghost_recent_bytes += value[0]
        else:
            self.ghost_protected[key] = value
            self.ghost_protected_bytes += value[0]
        self._ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self._ghost_bytes > self._ghost_limit or
               len(self.ghost_recent) + len(self.ghost_protected) > self._ghost_count_limit):
            source = None
            kind = 0
            serial = None
            if self.ghost_recent:
                source = self.ghost_recent
                kind = 1
                serial = next(iter(source.values()))[1]
            if self.ghost_protected:
                other_serial = next(iter(self.ghost_protected.values()))[1]
                if serial is None or other_serial < serial:
                    source = self.ghost_protected
                    kind = 2
            if source is None:
                break
            _, value = source.popitem(last=False)
            if kind == 1:
                self.ghost_recent_bytes -= value[0]
            else:
                self.ghost_protected_bytes -= value[0]
            self._ghost_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        left = self.ghost_recent_bytes
        right = self.ghost_protected_bytes
        if kind == 1:
            delta = self.capacity if left == 0 else max(1, min(self.capacity, right // left or 1))
            self.recent_target = min(self.capacity, self.recent_target + delta)
        else:
            delta = self.capacity if right == 0 else max(1, min(self.capacity, left // right or 1))
            self.recent_target = max(0, self.recent_target - delta)

    def _evict_one(self, prefer_recent):
        if prefer_recent and self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 1)
            return key
        if self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
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
            key = self._evict_one(self.recent_bytes > self.recent_target)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def _put_recent(self, key, size):
        self.recent[key] = size
        self.recent_bytes += size
        self.used += size

    def _put_protected(self, key, size):
        self.protected[key] = size
        self.protected_bytes += size
        self.used += size

    def _remove_resident(self, key):
        value = self.recent.pop(key, None)
        if value is not None:
            self.recent_bytes -= value
            self.used -= value
            return True
        value = self.protected.pop(key, None)
        if value is not None:
            self.protected_bytes -= value
            self.used -= value
            return True
        return False

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))

        resident = key in self.recent or key in self.protected
        if resident:
            was_recent = key in self.recent
            self._remove_resident(key)
            if size > self.capacity:
                return [key]
            evicted = self._make_room(size)
            self._discard_ghost(key)
            self._put_protected(key, size)
            return evicted

        ghost_kind = 1 if key in self.ghost_recent else 2 if key in self.ghost_protected else 0
        if ghost_kind:
            self._adjust_target(ghost_kind)
            self._discard_ghost(key)
        if size > self.capacity:
            return []

        evicted = self._make_room(size)
        if ghost_kind:
            self._put_protected(key, size)
        else:
            self._put_recent(key, size)
        return evicted
