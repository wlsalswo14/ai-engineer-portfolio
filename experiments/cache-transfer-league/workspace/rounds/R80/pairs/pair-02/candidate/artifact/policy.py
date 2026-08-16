from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.used = 0
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.recent_target = self.capacity // 2
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_bytes = 0
        self.serial = 0

    def _remove_ghost(self, key):
        value = self.ghost_recent.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]
        value = self.ghost_frequent.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]

    def _add_ghost(self, key, size, frequent):
        self._remove_ghost(key)
        self.serial += 1
        value = (size, self.serial)
        target = self.ghost_frequent if frequent else self.ghost_recent
        target[key] = value
        self.ghost_bytes += size
        while self.ghost_bytes > self.ghost_limit:
            oldest_kind = None
            oldest_serial = None
            for kind, ghosts in ((0, self.ghost_recent), (1, self.ghost_frequent)):
                if ghosts:
                    serial = next(iter(ghosts.values()))[1]
                    if oldest_serial is None or serial < oldest_serial:
                        oldest_kind = kind
                        oldest_serial = serial
            ghosts = self.ghost_frequent if oldest_kind else self.ghost_recent
            _, value = ghosts.popitem(last=False)
            self.ghost_bytes -= value[0]

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
        return 0, False

    def _evict_one(self, prefer_recent):
        if prefer_recent and self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self.used -= size
            self._add_ghost(key, size, False)
            return key
        if self.frequent:
            key, size = self.frequent.popitem(last=False)
            self.frequent_bytes -= size
            self.used -= size
            self._add_ghost(key, size, True)
            return key
        if self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self.used -= size
            self._add_ghost(key, size, False)
            return key
        return None

    def _make_room(self, incoming, ghost_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            prefer_recent = self.recent_bytes > self.recent_target
            if ghost_kind == 0 and self.recent_bytes >= self.recent_target:
                prefer_recent = True
            key = self._evict_one(prefer_recent)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def _adapt(self, ghost_kind):
        if not self.capacity:
            return
        r = sum(v[0] for v in self.ghost_recent.values())
        f = sum(v[0] for v in self.ghost_frequent.values())
        if ghost_kind == 0:
            delta = self.capacity if not r else max(1, min(self.capacity, f // r or 1))
            self.recent_target = min(self.capacity, self.recent_target + delta)
        else:
            delta = self.capacity if not f else max(1, min(self.capacity, r // f or 1))
            self.recent_target = max(0, self.recent_target - delta)

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))

        if key in self.recent:
            old = self.recent.pop(key)
            self.recent_bytes -= old
            self.used -= old
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 1)
            self.frequent[key] = size
            self.frequent_bytes += size
            self.used += size
            self._remove_ghost(key)
            return evicted

        if key in self.frequent:
            old = self.frequent.pop(key)
            self.frequent_bytes -= old
            self.used -= old
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 1)
            self.frequent[key] = size
            self.frequent_bytes += size
            self.used += size
            return evicted

        ghost_kind = 0
        if key in self.ghost_recent:
            ghost_kind = 0
        elif key in self.ghost_frequent:
            ghost_kind = 1

        if size <= 0 or size > self.capacity:
            return []

        if ghost_kind:
            self._adapt(ghost_kind)
            self._remove_ghost(key)
            evicted = self._make_room(size, ghost_kind)
            self.frequent[key] = size
            self.frequent_bytes += size
        else:
            evicted = self._make_room(size, ghost_kind)
            self.recent[key] = size
            self.recent_bytes += size
        self.used += size
        return evicted
