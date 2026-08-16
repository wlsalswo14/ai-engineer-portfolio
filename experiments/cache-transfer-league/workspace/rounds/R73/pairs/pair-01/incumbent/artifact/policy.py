from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        try:
            capacity_bytes = int(capacity_bytes)
        except Exception:
            capacity_bytes = 0
        self.capacity = max(0, capacity_bytes)
        self.target = self.capacity // 2
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.resident = {}
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.ghost_limit = 4096

    def _ghost_add(self, key, segment):
        self.ghost_recent.pop(key, None)
        self.ghost_frequent.pop(key, None)
        ghosts = self.ghost_recent if segment == 0 else self.ghost_frequent
        ghosts[key] = None
        ghosts.move_to_end(key)
        while len(ghosts) > self.ghost_limit:
            ghosts.popitem(last=False)

    def _remove_resident(self, key, remember=True):
        record = self.resident.pop(key, None)
        if record is None:
            return False
        size, segment = record
        if segment == 0:
            self.recent.pop(key, None)
            self.recent_bytes -= size
        else:
            self.frequent.pop(key, None)
            self.frequent_bytes -= size
        if remember:
            self._ghost_add(key, segment)
        return True

    def _candidate(self, mapping, protected):
        for key in mapping:
            if key != protected:
                return key
        return None

    def _make_room(self, needed, protected=None):
        evicted = []
        while self.recent_bytes + self.frequent_bytes + needed > self.capacity:
            prefer_recent = self.recent_bytes > self.target or not self.frequent
            first = self.recent if prefer_recent else self.frequent
            second = self.frequent if prefer_recent else self.recent
            victim = self._candidate(first, protected)
            if victim is None:
                victim = self._candidate(second, protected)
            if victim is None:
                break
            self._remove_resident(victim, remember=True)
            evicted.append(victim)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        try:
            size = int(size)
        except Exception:
            size = 0
        size = max(0, size)

        existing = self.resident.get(key)
        if existing is not None:
            if size > self.capacity:
                self._remove_resident(key, remember=True)
                return [key]

            old_size, segment = existing
            if segment == 0:
                self.recent.pop(key, None)
                self.recent_bytes -= old_size
                self.frequent[key] = old_size
                self.frequent.move_to_end(key)
                self.frequent_bytes += old_size
                segment = 1
            else:
                self.frequent.move_to_end(key)

            self.frequent[key] = size
            self.frequent.move_to_end(key)
            self.frequent_bytes += size - old_size
            self.resident[key] = (size, segment)
            return self._make_room(0, protected=key)

        if size > self.capacity:
            return []

        recent_ghost = key in self.ghost_recent
        frequent_ghost = key in self.ghost_frequent
        self.ghost_recent.pop(key, None)
        self.ghost_frequent.pop(key, None)

        step = max(1, self.capacity // 8)
        if recent_ghost:
            self.target = min(self.capacity, self.target + step)
            segment = 1
        elif frequent_ghost:
            self.target = max(0, self.target - step)
            segment = 1
        else:
            segment = 0

        evicted = self._make_room(size)
        self.resident[key] = (size, segment)
        if segment == 0:
            self.recent[key] = size
            self.recent.move_to_end(key)
            self.recent_bytes += size
        else:
            self.frequent[key] = size
            self.frequent.move_to_end(key)
            self.frequent_bytes += size
        return evicted
