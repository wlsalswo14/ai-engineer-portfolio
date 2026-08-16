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
        self.ghost_bytes = 0
        self.target_recent = self.capacity // 2
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096
        self.serial = 0

    def _remove_ghost(self, key):
        value = self.ghost_recent.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value
        value = self.ghost_frequent.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value

    def _remember_ghost(self, key, size, frequent):
        self._remove_ghost(key)
        remembered = max(1, int(size))
        if frequent:
            self.ghost_frequent[key] = remembered
        else:
            self.ghost_recent[key] = remembered
        self.ghost_bytes += remembered
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_recent) + len(self.ghost_frequent) > self.ghost_count_limit):
            recent_key = next(iter(self.ghost_recent), None)
            frequent_key = next(iter(self.ghost_frequent), None)
            if recent_key is None:
                self.ghost_bytes -= self.ghost_frequent.pop(frequent_key)
            elif frequent_key is None:
                self.ghost_bytes -= self.ghost_recent.pop(recent_key)
            else:
                recent_value = self.ghost_recent[recent_key]
                frequent_value = self.ghost_frequent[frequent_key]
                if recent_value <= frequent_value:
                    self.ghost_bytes -= self.ghost_recent.pop(recent_key)
                else:
                    self.ghost_bytes -= self.ghost_frequent.pop(frequent_key)

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        if kind == 1:
            a = self.ghost_recent_bytes()
            b = self.ghost_frequent_bytes()
            delta = self.capacity if a == 0 else max(1, min(self.capacity, b // a or 1))
            self.target_recent = min(self.capacity, self.target_recent + delta)
        else:
            a = self.ghost_recent_bytes()
            b = self.ghost_frequent_bytes()
            delta = self.capacity if b == 0 else max(1, min(self.capacity, a // b or 1))
            self.target_recent = max(0, self.target_recent - delta)

    def ghost_recent_bytes(self):
        return sum(self.ghost_recent.values())

    def ghost_frequent_bytes(self):
        return sum(self.ghost_frequent.values())

    def _remove_resident(self, key):
        value = self.recent.pop(key, None)
        if value is not None:
            self.recent_bytes -= value
            return value, False
        value = self.frequent.pop(key, None)
        if value is not None:
            self.frequent_bytes -= value
            return value, True
        return 0, False

    def _evict_one(self):
        if self.recent and (self.recent_bytes > self.target_recent or not self.frequent):
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self._remember_ghost(key, size, False)
            return key
        if self.frequent:
            key, size = self.frequent.popitem(last=False)
            self.frequent_bytes -= size
            self._remember_ghost(key, size, True)
            return key
        if self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self._remember_ghost(key, size, False)
            return key
        return None

    def _make_room(self, incoming):
        evicted = []
        used = self.recent_bytes + self.frequent_bytes
        while used + incoming > self.capacity:
            key = self._evict_one()
            if key is None:
                break
            evicted.append(key)
            used = self.recent_bytes + self.frequent_bytes
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))

        if key in self.recent or key in self.frequent:
            old_size, was_frequent = self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size)
            self._remove_ghost(key)
            self.frequent[key] = size
            self.frequent_bytes += size
            return evicted

        if size <= 0 or size > self.capacity:
            return []

        if key in self.ghost_recent:
            self._adjust_target(1)
            self._remove_ghost(key)
            frequent = True
        elif key in self.ghost_frequent:
            self._adjust_target(2)
            self._remove_ghost(key)
            frequent = True
        else:
            frequent = False

        evicted = self._make_room(size)
        if frequent:
            self.frequent[key] = size
            self.frequent_bytes += size
        else:
            self.recent[key] = size
            self.recent_bytes += size
        return evicted
