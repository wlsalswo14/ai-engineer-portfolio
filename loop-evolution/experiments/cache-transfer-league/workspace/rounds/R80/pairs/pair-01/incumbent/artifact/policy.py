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
        self.protected_target = self.capacity // 2
        self.ghost_bytes = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096

    def _drop_ghost(self, key):
        value = self.ghost_recent.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value
        value = self.ghost_protected.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value

    def _remember_ghost(self, key, size, protected):
        self._drop_ghost(key)
        value = max(1, int(size))
        target = self.ghost_protected if protected else self.ghost_recent
        target[key] = value
        self.ghost_bytes += value
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_recent) + len(self.ghost_protected) > self.ghost_count_limit):
            if self.ghost_recent and self.ghost_protected:
                if next(iter(self.ghost_recent)) < next(iter(self.ghost_protected)):
                    target = self.ghost_recent
                else:
                    target = self.ghost_protected
            elif self.ghost_recent:
                target = self.ghost_recent
            else:
                target = self.ghost_protected
            _, size = target.popitem(last=False)
            self.ghost_bytes -= size

    def _adjust_target(self, protected_hit):
        if self.capacity <= 0:
            return
        if protected_hit:
            ratio = (self.ghost_recent_bytes() //
                     max(1, self.ghost_protected_bytes()))
            self.protected_target = max(0, self.protected_target - max(1, min(self.capacity, ratio)))
        else:
            ratio = (self.ghost_protected_bytes() //
                     max(1, self.ghost_recent_bytes()))
            self.protected_target = min(self.capacity, self.protected_target + max(1, min(self.capacity, ratio)))

    def ghost_recent_bytes(self):
        return sum(self.ghost_recent.values())

    def ghost_protected_bytes(self):
        return sum(self.ghost_protected.values())

    def _remove_resident(self, key):
        value = self.recent.pop(key, None)
        if value is not None:
            self.recent_bytes -= value
            self.used -= value
            return value, False
        value = self.protected.pop(key, None)
        if value is not None:
            self.protected_bytes -= value
            self.used -= value
            return value, True
        return 0, False

    def _evict_one(self):
        if self.recent and (self.recent_bytes > self.protected_target or not self.protected):
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

        resident = key in self.recent or key in self.protected
        if resident:
            old_size, was_protected = self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size)
            self._drop_ghost(key)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            return evicted

        in_recent_ghost = key in self.ghost_recent
        in_protected_ghost = key in self.ghost_protected
        if size <= 0 or size > self.capacity:
            return []

        if in_recent_ghost:
            self._adjust_target(False)
        elif in_protected_ghost:
            self._adjust_target(True)
        self._drop_ghost(key)

        evicted = self._make_room(size)
        if in_recent_ghost or in_protected_ghost:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.recent[key] = size
            self.recent_bytes += size
        self.used += size
        return evicted
