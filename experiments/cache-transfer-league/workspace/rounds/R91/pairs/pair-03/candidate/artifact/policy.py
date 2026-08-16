class Policy:
    def __init__(self, capacity_bytes):
        try:
            capacity = int(capacity_bytes)
        except Exception:
            capacity = 0
        self.capacity_bytes = max(0, capacity)
        self._items = {}
        self._used = 0
        self._tick = 0
        self._serial = 0

    def access(self, key, size, now):
        self._tick += 1
        tick = self._tick
        normalized = self._normalize_size(size)

        if normalized is None:
            return []

        if normalized > self.capacity_bytes:
            return self._evict_all()

        if normalized == 0:
            return []

        if key in self._items:
            item = self._items[key]
            old_size = item[0]
            self._used += normalized - old_size
            item[0] = normalized
            gap = tick - item[1]
            item[4] = gap if gap > 0 else item[4]
            item[1] = tick
            item[2] = min(1024, item[2] + 1)
            item[3] += 1
            if item[2] >= 2:
                item[5] = True
            return self._trim(normalized)

        self._serial += 1
        self._items[key] = [normalized, tick, 1, 1, 0, False, self._serial]
        self._used += normalized
        return self._trim(normalized)

    def _normalize_size(self, size):
        try:
            value = int(size)
        except Exception:
            return None
        if value < 0:
            return None
        return value

    def _trim(self, incoming_size):
        evicted = []
        while self._used > self.capacity_bytes and self._items:
            victim = self._victim(incoming_size)
            if victim is None:
                break
            item = self._items.pop(victim)
            self._used -= item[0]
            evicted.append(victim)
        evicted.sort()
        return evicted

    def _victim(self, incoming_size):
        scale = float(max(1, self.capacity_bytes))
        best_key = None
        best_rank = None
        for key, item in self._items.items():
            age = max(0, self._tick - item[1])
            effective_frequency = float(item[2]) / (1.0 + age / 8.0)
            freshness = 1.0 / (1.0 + age)
            reuse = 1.0 / (1.0 + max(0, item[4]))
            protected = 0.0
            if item[5] and age <= max(8, item[4] * 2):
                protected = 2.0
            byte_hits = 0.0
            if item[2] > 1:
                byte_hits = min(2.0, ((item[2] - 1) * item[0]) / max(1.0, scale * 0.25))
            size_pressure = 3.0 * (float(item[0]) / scale)
            retention = (2.0 * effective_frequency + protected + freshness + reuse + byte_hits - size_pressure)
            rank = (retention, item[1], item[6])
            if best_rank is None or rank < best_rank:
                best_rank = rank
                best_key = key
        return best_key

    def _evict_all(self):
        evicted = list(self._items.keys())
        self._items.clear()
        self._used = 0
        evicted.sort()
        return evicted
