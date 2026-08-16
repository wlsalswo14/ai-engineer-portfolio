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
        if protected:
            self.ghost_protected[key] = value
        else:
            self.ghost_recent[key] = value
        self.ghost_bytes += value
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_recent) + len(self.ghost_protected) > self.ghost_count_limit):
            source = self.ghost_recent
            if not source or (self.ghost_protected and
                              next(iter(self.ghost_protected)) < next(iter(source))):
                source = self.ghost_protected
            if not source:
                source = self.ghost_recent
            _, value = source.popitem(last=False)
            self.ghost_bytes -= value

    def _adapt(self, mode):
        if self.capacity <= 0:
            return
        recent = sum(self.ghost_recent.values())
        protected = sum(self.ghost_protected.values())
        if mode == 1:
            delta = self.capacity if recent == 0 else max(1, min(self.capacity, protected // recent or 1))
            self.target = min(self.capacity, self.target + delta)
        elif mode == 2:
            delta = self.capacity if protected == 0 else max(1, min(self.capacity, recent // protected or 1))
            self.target = max(0, self.target - delta)

    def _remove(self, key):
        value = self.recent.pop(key, None)
        if value is not None:
            self.recent_bytes -= value
            self.used -= value
            return False, value
        value = self.protected.pop(key, None)
        if value is not None:
            self.protected_bytes -= value
            self.used -= value
            return True, value
        return None, None

    def _evict_one(self, mode):
        choose_recent = False
        if mode == 1 and self.recent and self.recent_bytes >= self.target:
            choose_recent = True
        elif mode == 2 and self.protected and self.recent_bytes <= self.target:
            choose_recent = False
        elif self.recent and self.recent_bytes > self.target:
            choose_recent = True
        elif self.recent and not self.protected:
            choose_recent = True

        if choose_recent and self.recent:
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

        in_recent = key in self.recent
        in_protected = key in self.protected
        if in_recent or in_protected:
            was_protected, old_size = self._remove(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            if self.used + size > self.capacity:
                return evicted + [key]
            self._drop_ghost(key)
            if was_protected:
                self.protected[key] = size
                self.protected_bytes += size
            else:
                self.protected[key] = size
                self.protected_bytes += size
            self.used += size
            return evicted

        mode = 1 if key in self.ghost_recent else 2 if key in self.ghost_protected else 0
        if size <= 0 or size > self.capacity:
            return []
        if mode:
            self._adapt(mode)
            self._drop_ghost(key)

        evicted = self._make_room(size, mode)
        if self.used + size > self.capacity:
            return evicted
        if mode:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.recent[key] = size
            self.recent_bytes += size
        self.used += size
        return evicted
