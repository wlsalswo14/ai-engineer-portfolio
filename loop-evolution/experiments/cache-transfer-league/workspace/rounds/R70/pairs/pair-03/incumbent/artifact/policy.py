class Policy:
    def __init__(self, capacity_bytes: int):
        try:
            capacity = int(capacity_bytes)
        except (TypeError, ValueError, OverflowError):
            capacity = 0
        self.capacity_bytes = max(0, capacity)
        self.used_bytes = 0
        self.recent_bytes = 0
        self.recent_target = self.capacity_bytes // 2
        self.resident = {}
        self.ghost_recent = {}
        self.ghost_frequent = {}
        self.ghost_limit = 1024
        self.tick = 0

    def _remember_ghost(self, key, size, frequency, segment):
        self.ghost_recent.pop(key, None)
        self.ghost_frequent.pop(key, None)
        target = self.ghost_recent if segment == 0 else self.ghost_frequent
        target[key] = (size, frequency, self.tick)
        while len(self.ghost_recent) + len(self.ghost_frequent) > self.ghost_limit:
            oldest_source = None
            oldest_key = None
            oldest_tick = None
            for source in (self.ghost_recent, self.ghost_frequent):
                for candidate, data in source.items():
                    if oldest_tick is None or data[2] < oldest_tick:
                        oldest_source = source
                        oldest_key = candidate
                        oldest_tick = data[2]
            if oldest_source is None:
                break
            oldest_source.pop(oldest_key, None)

    def _remove(self, key):
        entry = self.resident.pop(key, None)
        if entry is None:
            return False
        size, frequency, last, segment = entry
        self.used_bytes -= size
        if segment == 0:
            self.recent_bytes -= size
        if self.used_bytes < 0:
            self.used_bytes = 0
        if self.recent_bytes < 0:
            self.recent_bytes = 0
        self._remember_ghost(key, size, frequency, segment)
        return True

    def _choose_victim(self, protected):
        if not self.resident:
            return None
        frequent_bytes = self.used_bytes - self.recent_bytes
        if self.recent_bytes > self.recent_target:
            candidates = [(key, entry) for key, entry in self.resident.items()
                          if key != protected and entry[3] == 0]
        elif frequent_bytes > self.capacity_bytes - self.recent_target:
            candidates = [(key, entry) for key, entry in self.resident.items()
                          if key != protected and entry[3] == 1]
        else:
            candidates = [(key, entry) for key, entry in self.resident.items()
                          if key != protected]
        if not candidates:
            candidates = [(key, entry) for key, entry in self.resident.items()
                          if key != protected]
        if not candidates:
            return None
        return min(candidates, key=lambda item: (item[1][1], item[1][2], item[1][0], item[0]))[0]

    def _trim(self, protected, evicted):
        while self.used_bytes > self.capacity_bytes:
            victim = self._choose_victim(protected)
            if victim is None or not self._remove(victim):
                break
            evicted.append(victim)

    def access(self, key: int, size: int, now: int) -> list[int]:
        try:
            key = int(key)
        except (TypeError, ValueError, OverflowError):
            return []
        try:
            size = max(0, int(size))
        except (TypeError, ValueError, OverflowError):
            size = 0
        self.tick += 1
        evicted = []

        if key in self.resident:
            old_size, frequency, last, segment = self.resident[key]
            if size > self.capacity_bytes or self.capacity_bytes == 0:
                if self._remove(key):
                    evicted.append(key)
                return evicted
            self.used_bytes -= old_size
            if segment == 0:
                self.recent_bytes -= old_size
            frequency = min(65535, frequency + 1)
            segment = 1 if segment == 1 or frequency >= 2 else 0
            self.resident[key] = (size, frequency, self.tick, segment)
            self.used_bytes += size
            if segment == 0:
                self.recent_bytes += size
            self._trim(key, evicted)
            return evicted

        ghost = self.ghost_recent.pop(key, None)
        if ghost is not None:
            self.recent_target = min(self.capacity_bytes,
                                     self.recent_target + max(1, ghost[0]))
            frequency = min(65535, max(2, ghost[1] + 1))
            segment = 1
        else:
            ghost = self.ghost_frequent.pop(key, None)
            if ghost is not None:
                self.recent_target = max(0,
                                         self.recent_target - max(1, ghost[0]))
                frequency = min(65535, max(2, ghost[1] + 1))
                segment = 1
            else:
                frequency = 1
                segment = 0
        self.ghost_recent.pop(key, None)
        self.ghost_frequent.pop(key, None)

        if size > self.capacity_bytes or self.capacity_bytes == 0:
            return evicted
        self.resident[key] = (size, frequency, self.tick, segment)
        self.used_bytes += size
        if segment == 0:
            self.recent_bytes += size
        self._trim(key, evicted)
        return evicted
