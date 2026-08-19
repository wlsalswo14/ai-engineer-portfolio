from collections import OrderedDict

class Policy:
    def __init__(self, capacity_bytes):
        try:
            capacity = int(capacity_bytes)
        except (TypeError, ValueError, OverflowError):
            capacity = 0
        self.capacity_bytes = max(0, capacity)
        self.target_recent = self.capacity_bytes // 2
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.recent_ghost = OrderedDict()
        self.frequent_ghost = OrderedDict()
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.ghost_limit = 4096
        self.max_resident_entries = 8192

    def _drop_ghost(self, key):
        self.recent_ghost.pop(key, None)
        self.frequent_ghost.pop(key, None)

    def _remember_ghost(self, key, size, frequent):
        self._drop_ghost(key)
        table = self.frequent_ghost if frequent else self.recent_ghost
        table[key] = size
        while len(table) > self.ghost_limit:
            table.popitem(last=False)

    def _trim(self, evicted):
        while (self.recent_bytes + self.frequent_bytes > self.capacity_bytes or
               len(self.recent) + len(self.frequent) > self.max_resident_entries):
            if self.recent and (self.recent_bytes > self.target_recent or not self.frequent):
                key, size = self.recent.popitem(last=False)
                self.recent_bytes -= size
                self._remember_ghost(key, size, False)
            elif self.frequent:
                key, size = self.frequent.popitem(last=False)
                self.frequent_bytes -= size
                self._remember_ghost(key, size, True)
            elif self.recent:
                key, size = self.recent.popitem(last=False)
                self.recent_bytes -= size
                self._remember_ghost(key, size, False)
            else:
                break
            evicted.append(key)

    def access(self, key, size, now):
        try:
            weight = int(size)
        except (TypeError, ValueError, OverflowError):
            weight = 0
        weight = max(0, weight)
        evicted = []

        if key in self.recent:
            old = self.recent.pop(key)
            self.recent_bytes -= old
            if weight > self.capacity_bytes:
                self._drop_ghost(key)
                return [key]
            self.frequent[key] = weight
            self.frequent_bytes += weight
            self._drop_ghost(key)
            self._trim(evicted)
            return evicted

        if key in self.frequent:
            old = self.frequent.pop(key)
            self.frequent_bytes -= old
            if weight > self.capacity_bytes:
                self._drop_ghost(key)
                return [key]
            self.frequent[key] = weight
            self.frequent_bytes += weight
            self._drop_ghost(key)
            self._trim(evicted)
            return evicted

        ghost_recent = key in self.recent_ghost
        ghost_frequent = key in self.frequent_ghost
        self._drop_ghost(key)

        if self.capacity_bytes == 0 or weight > self.capacity_bytes:
            return evicted

        if ghost_recent:
            self.target_recent = min(
                self.capacity_bytes,
                self.target_recent + max(1, min(weight, self.capacity_bytes))
            )
            self.frequent[key] = weight
            self.frequent_bytes += weight
        elif ghost_frequent:
            self.target_recent = max(
                0,
                self.target_recent - max(1, min(weight, self.capacity_bytes))
            )
            self.frequent[key] = weight
            self.frequent_bytes += weight
        else:
            self.recent[key] = weight
            self.recent_bytes += weight

        self._trim(evicted)
        return evicted
