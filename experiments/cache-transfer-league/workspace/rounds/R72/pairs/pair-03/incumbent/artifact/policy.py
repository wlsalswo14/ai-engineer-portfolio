from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.recent_target = self.capacity // 2
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.ghost_order = OrderedDict()
        self.ghost_recent_bytes = 0
        self.ghost_frequent_bytes = 0
        self.ghost_limit_bytes = self.capacity * 2
        self.ghost_limit_count = 4096

    def _drop_ghost(self, key):
        item = self.ghost_order.pop(key, None)
        if item is None:
            return
        source, value = item
        store = self.ghost_recent if source == 'recent' else self.ghost_frequent
        if key in store:
            del store[key]
            if source == 'recent':
                self.ghost_recent_bytes -= value
            else:
                self.ghost_frequent_bytes -= value

    def _trim_ghosts(self):
        while self.ghost_order and (
            len(self.ghost_order) > self.ghost_limit_count
            or self.ghost_recent_bytes + self.ghost_frequent_bytes > self.ghost_limit_bytes
        ):
            key, _ = self.ghost_order.popitem(last=False)
            if key in self.ghost_recent:
                value = self.ghost_recent.pop(key)
                self.ghost_recent_bytes -= value
            elif key in self.ghost_frequent:
                value = self.ghost_frequent.pop(key)
                self.ghost_frequent_bytes -= value

    def _add_ghost(self, key, value, source):
        self._drop_ghost(key)
        store = self.ghost_recent if source == 'recent' else self.ghost_frequent
        store[key] = value
        self.ghost_order[key] = (source, value)
        if source == 'recent':
            self.ghost_recent_bytes += value
        else:
            self.ghost_frequent_bytes += value
        self._trim_ghosts()

    def _adjust_target(self, source):
        if self.capacity <= 0:
            return
        if source == 'recent':
            delta = max(1, self.ghost_frequent_bytes // max(1, self.ghost_recent_bytes))
            self.recent_target = min(self.capacity, self.recent_target + delta)
        else:
            delta = max(1, self.ghost_recent_bytes // max(1, self.ghost_frequent_bytes))
            self.recent_target = max(0, self.recent_target - delta)

    def _choose_victim(self, protected=None):
        if self.recent_bytes > self.recent_target:
            stores = (('recent', self.recent), ('frequent', self.frequent))
        else:
            stores = (('frequent', self.frequent), ('recent', self.recent))
        for source, store in stores:
            for key in store:
                if key != protected:
                    return source, key
        return None

    def _evict_one(self, source, key):
        store = self.recent if source == 'recent' else self.frequent
        value = store.pop(key)
        if source == 'recent':
            self.recent_bytes -= value
        else:
            self.frequent_bytes -= value
        self._add_ghost(key, value, source)
        return key

    def _make_room(self, incoming, protected=None):
        evicted = []
        while self.recent_bytes + self.frequent_bytes + incoming > self.capacity:
            victim = self._choose_victim(protected)
            if victim is None:
                break
            evicted.append(self._evict_one(victim[0], victim[1]))
        return evicted

    def _evict_all(self):
        evicted = []
        while self.recent or self.frequent:
            victim = self._choose_victim()
            if victim is None:
                break
            evicted.append(self._evict_one(victim[0], victim[1]))
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        value = max(0, int(size))

        if self.capacity == 0:
            self._drop_ghost(key)
            return self._evict_all()

        if key in self.recent:
            old = self.recent.pop(key)
            self.recent_bytes -= old
            if value > self.capacity:
                return [key]
            self.frequent[key] = value
            self.frequent_bytes += value
            return self._make_room(value, key)

        if key in self.frequent:
            old = self.frequent.pop(key)
            self.frequent_bytes -= old
            if value > self.capacity:
                return [key]
            self.frequent[key] = value
            self.frequent_bytes += value
            return self._make_room(value, key)

        if value > self.capacity:
            self._drop_ghost(key)
            return []

        if key in self.ghost_recent:
            self._adjust_target('recent')
            self._drop_ghost(key)
            self.frequent[key] = value
            self.frequent_bytes += value
        elif key in self.ghost_frequent:
            self._adjust_target('frequent')
            self._drop_ghost(key)
            self.frequent[key] = value
            self.frequent_bytes += value
        else:
            self._drop_ghost(key)
            self.recent[key] = value
            self.recent_bytes += value

        return self._make_room(value, key)
