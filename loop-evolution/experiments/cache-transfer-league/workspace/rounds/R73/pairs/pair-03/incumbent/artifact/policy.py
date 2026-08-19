from collections import OrderedDict

class Policy:
    def __init__(self, capacity_bytes):
        self.capacity = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.resident_bytes = 0
        self.recent_target = self.capacity // 2
        self.ghost_limit = 4096

    def _discard_ghost(self, key):
        self.ghost_recent.pop(key, None)
        self.ghost_frequent.pop(key, None)

    def _remember(self, ghost, key):
        self._discard_ghost(key)
        ghost[key] = None
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _remove_resident(self, key):
        if key in self.recent:
            size = self.recent.pop(key)
            self.recent_bytes -= size
        else:
            size = self.frequent.pop(key)
            self.frequent_bytes -= size
        self.resident_bytes -= size
        return size

    def _oldest_available(self, segment, protected):
        for key in segment:
            if key != protected:
                return key
        return None

    def _trim(self, protected=None):
        evicted = []
        while self.resident_bytes > self.capacity:
            segment = None
            is_recent = False
            if self.recent and (self.recent_bytes > self.recent_target or not self.frequent):
                segment = self.recent
                is_recent = True
            elif self.frequent:
                segment = self.frequent
            elif self.recent:
                segment = self.recent
                is_recent = True
            if segment is None:
                break
            key = self._oldest_available(segment, protected)
            if key is None:
                other = self.frequent if segment is self.recent else self.recent
                if other:
                    segment = other
                    is_recent = segment is self.recent
                    key = self._oldest_available(segment, protected)
            if key is None:
                break
            size = segment.pop(key)
            if is_recent:
                self.recent_bytes -= size
                self._remember(self.ghost_recent, key)
            else:
                self.frequent_bytes -= size
                self._remember(self.ghost_frequent, key)
            self.resident_bytes -= size
            evicted.append(key)
        return evicted

    def access(self, key, size, now):
        size = max(0, int(size))
        resident = key in self.recent or key in self.frequent

        if resident:
            if size > self.capacity:
                self._remove_resident(key)
                self._discard_ghost(key)
                return [key]
            self._remove_resident(key)
            self.frequent[key] = size
            self.frequent_bytes += size
            self.resident_bytes += size
            self._discard_ghost(key)
            return self._trim(protected=key)

        recent_ghost = key in self.ghost_recent
        frequent_ghost = key in self.ghost_frequent
        if size > self.capacity:
            self._discard_ghost(key)
            return []

        step = max(1, self.capacity // 8)
        if recent_ghost:
            self.recent_target = min(self.capacity, self.recent_target + step)
            self._discard_ghost(key)
            self.frequent[key] = size
            self.frequent_bytes += size
        elif frequent_ghost:
            self.recent_target = max(0, self.recent_target - step)
            self._discard_ghost(key)
            self.frequent[key] = size
            self.frequent_bytes += size
        else:
            self._discard_ghost(key)
            self.recent[key] = size
            self.recent_bytes += size

        self.resident_bytes += size
        return self._trim(protected=key)
