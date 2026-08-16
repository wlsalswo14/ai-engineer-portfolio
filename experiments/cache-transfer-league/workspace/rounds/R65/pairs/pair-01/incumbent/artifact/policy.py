from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, self._to_int(capacity_bytes))
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.used = 0
        self.recent_target = self.capacity // 2
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.ghost_recent_bytes = 0
        self.ghost_frequent_bytes = 0
        self.ghost_order = OrderedDict()
        self.max_ghost_bytes = self.capacity * 2
        self.max_ghost_count = 128

    @staticmethod
    def _to_int(value):
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return 0

    def _remove_ghost(self, key):
        value = self.ghost_recent.pop(key, None)
        if value is not None:
            self.ghost_recent_bytes -= value
            self.ghost_order.pop(key, None)
            return 'recent'
        value = self.ghost_frequent.pop(key, None)
        if value is not None:
            self.ghost_frequent_bytes -= value
            self.ghost_order.pop(key, None)
            return 'frequent'
        return None

    def _trim_ghosts(self):
        while (len(self.ghost_order) > self.max_ghost_count or
               self.ghost_recent_bytes + self.ghost_frequent_bytes > self.max_ghost_bytes):
            key, segment = self.ghost_order.popitem(last=False)
            table = self.ghost_recent if segment == 'recent' else self.ghost_frequent
            value = table.pop(key, None)
            if value is not None:
                if segment == 'recent':
                    self.ghost_recent_bytes -= value
                else:
                    self.ghost_frequent_bytes -= value

    def _add_ghost(self, segment, key, size):
        if self.max_ghost_bytes <= 0 or size > self.max_ghost_bytes:
            return
        self._remove_ghost(key)
        table = self.ghost_recent if segment == 'recent' else self.ghost_frequent
        table[key] = size
        if segment == 'recent':
            self.ghost_recent_bytes += size
        else:
            self.ghost_frequent_bytes += size
        self.ghost_order[key] = segment
        self._trim_ghosts()

    def _take_resident(self, key):
        if key in self.recent:
            size = self.recent.pop(key)
            self.recent_bytes -= size
            self.used -= size
            return 'recent', size
        if key in self.frequent:
            size = self.frequent.pop(key)
            self.frequent_bytes -= size
            self.used -= size
            return 'frequent', size
        return None, None

    def _adjust_target(self, segment, size):
        if self.capacity <= 0:
            return
        own = self.ghost_recent_bytes if segment == 'recent' else self.ghost_frequent_bytes
        opposing = self.ghost_frequent_bytes if segment == 'recent' else self.ghost_recent_bytes
        scale = max(1, min(max(1, size), self.capacity))
        delta = max(1, (max(1, opposing) * scale) // max(1, own))
        delta = min(self.capacity, delta)
        if segment == 'recent':
            self.recent_target = min(self.capacity, self.recent_target + delta)
        else:
            self.recent_target = max(0, self.recent_target - delta)

    def _make_room(self, incoming, prefer_recent, evicted):
        while self.used + incoming > self.capacity:
            choose_recent = bool(self.recent) and (prefer_recent or self.recent_bytes > self.recent_target)
            if choose_recent:
                table = self.recent
                segment = 'recent'
            elif self.frequent:
                table = self.frequent
                segment = 'frequent'
            elif self.recent:
                table = self.recent
                segment = 'recent'
            else:
                break
            key, size = table.popitem(last=False)
            if segment == 'recent':
                self.recent_bytes -= size
            else:
                self.frequent_bytes -= size
            self.used -= size
            if key not in evicted:
                evicted.append(key)
            self._add_ghost(segment, key, size)

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = self._to_int(key)
        size = max(0, self._to_int(size))
        evicted = []

        resident_segment, _ = self._take_resident(key)
        if resident_segment is not None:
            self._remove_ghost(key)
            if size > self.capacity:
                evicted.append(key)
                return evicted
            self._make_room(size, False, evicted)
            if self.used + size <= self.capacity:
                self.frequent[key] = size
                self.frequent_bytes += size
                self.used += size
            elif key not in evicted:
                evicted.append(key)
            return evicted

        ghost_segment = None
        if key in self.ghost_recent:
            self._adjust_target('recent', size)
            self._remove_ghost(key)
            ghost_segment = 'recent'
        elif key in self.ghost_frequent:
            self._adjust_target('frequent', size)
            self._remove_ghost(key)
            ghost_segment = 'frequent'

        if size > self.capacity:
            return evicted

        self._make_room(size, ghost_segment == 'recent', evicted)
        self._remove_ghost(key)
        if self.used + size <= self.capacity:
            if ghost_segment is None:
                self.recent[key] = size
                self.recent_bytes += size
            else:
                self.frequent[key] = size
                self.frequent_bytes += size
            self.used += size
        return evicted
