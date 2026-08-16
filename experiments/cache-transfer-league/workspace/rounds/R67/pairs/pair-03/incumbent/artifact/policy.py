from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.target_recent = 0
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.ghost_recent_bytes = 0
        self.ghost_frequent_bytes = 0
        self.ghost_limit = 2048

    def _remove_ghost(self, kind, key):
        table = self.ghost_recent if kind == 'recent' else self.ghost_frequent
        value = table.pop(key, None)
        if value is not None:
            if kind == 'recent':
                self.ghost_recent_bytes -= value
            else:
                self.ghost_frequent_bytes -= value

    def _record_ghost(self, kind, key, size):
        self._remove_ghost('recent', key)
        self._remove_ghost('frequent', key)
        size = max(0, int(size))
        table = self.ghost_recent if kind == 'recent' else self.ghost_frequent
        table[key] = size
        if kind == 'recent':
            self.ghost_recent_bytes += size
            while table and (self.ghost_recent_bytes > self.capacity or len(table) > self.ghost_limit):
                _, value = table.popitem(last=False)
                self.ghost_recent_bytes -= value
        else:
            self.ghost_frequent_bytes += size
            while table and (self.ghost_frequent_bytes > self.capacity or len(table) > self.ghost_limit):
                _, value = table.popitem(last=False)
                self.ghost_frequent_bytes -= value

    def _adapt(self, kind):
        if kind == 'recent':
            delta = max(1, self.ghost_frequent_bytes // max(1, self.ghost_recent_bytes))
            self.target_recent = min(self.capacity, self.target_recent + delta)
        else:
            delta = max(1, self.ghost_recent_bytes // max(1, self.ghost_frequent_bytes))
            self.target_recent = max(0, self.target_recent - delta)

    def _evict_one(self, incoming_kind=None):
        prefer_recent = self.recent_bytes > self.target_recent
        if self.recent_bytes == self.target_recent and incoming_kind == 'frequent':
            prefer_recent = True
        if prefer_recent and self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self._record_ghost('recent', key, size)
            return key
        if self.frequent:
            key, size = self.frequent.popitem(last=False)
            self.frequent_bytes -= size
            self._record_ghost('frequent', key, size)
            return key
        if self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self._record_ghost('recent', key, size)
            return key
        return None

    def _admit(self, key, size, kind, incoming_kind=None):
        evicted = []
        while self.recent_bytes + self.frequent_bytes + size > self.capacity:
            victim = self._evict_one(incoming_kind)
            if victim is None:
                break
            evicted.append(victim)
        if kind == 'recent':
            self.recent[key] = size
            self.recent_bytes += size
        else:
            self.frequent[key] = size
            self.frequent_bytes += size
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        size = max(0, int(size))
        if key in self.recent:
            old_size = self.recent.pop(key)
            self.recent_bytes -= old_size
            if size > self.capacity:
                self._record_ghost('recent', key, old_size)
                return [key]
            return self._admit(key, size, 'frequent')
        if key in self.frequent:
            old_size = self.frequent.pop(key)
            self.frequent_bytes -= old_size
            if size > self.capacity:
                self._record_ghost('frequent', key, old_size)
                return [key]
            return self._admit(key, size, 'frequent')
        if size > self.capacity:
            return []
        if key in self.ghost_recent:
            self._adapt('recent')
            self._remove_ghost('recent', key)
            return self._admit(key, size, 'frequent', 'recent')
        if key in self.ghost_frequent:
            self._adapt('frequent')
            self._remove_ghost('frequent', key)
            return self._admit(key, size, 'frequent', 'frequent')
        return self._admit(key, size, 'recent')
