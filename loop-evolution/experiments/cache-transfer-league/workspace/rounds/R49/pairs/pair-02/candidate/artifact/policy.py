class Policy:
    def __init__(self, capacity_bytes):
        try:
            capacity = int(capacity_bytes)
        except Exception:
            capacity = 0
        self.capacity = max(0, capacity)
        self.used = 0
        self.tick = 0
        self.resident = {}
        self.frequency = {}
        self.ghost = {}
        self.window = 0
        self.window_misses = 0
        self.miss_pressure = 0.0

    def _observe(self, key):
        value = self.frequency.get(key, 0) + 1
        self.frequency[key] = min(255, value)
        if self.tick % 512 == 0:
            for observed in list(self.frequency):
                self.frequency[observed] = max(1, self.frequency[observed] // 2)
        if len(self.frequency) > 4096:
            victim = None
            lowest = None
            for observed, count in self.frequency.items():
                if lowest is None or count < lowest:
                    victim = observed
                    lowest = count
            if victim is not None:
                del self.frequency[victim]
        return self.frequency[key]

    def _remember_ghost(self, key, entry):
        self.ghost[key] = (self.tick, entry['freq'], entry['size'])
        if len(self.ghost) > 2048:
            oldest_key = None
            oldest_tick = None
            for observed, record in self.ghost.items():
                if oldest_tick is None or record[0] < oldest_tick:
                    oldest_key = observed
                    oldest_tick = record[0]
            if oldest_key is not None:
                del self.ghost[oldest_key]

    def _score(self, entry):
        age = max(0, self.tick - entry['last'])
        scale = 8.0 + 24.0 * self.miss_pressure
        recency = 1.0 / (1.0 + age / scale)
        frequency = 1.0 + (max(0, entry['freq'] - 1) ** 0.5)
        size_ratio = min(1.0, entry['size'] / float(max(1, self.capacity)))
        byte_value = 0.72 + 0.48 * (size_ratio ** 0.5)
        return byte_value * (1.65 * frequency + (1.0 + 0.75 * self.miss_pressure) * recency + 0.35 * entry['ghost'])

    def _victim(self, required):
        candidates = []
        fallback = []
        for key, entry in self.resident.items():
            if isinstance(key, int) and not isinstance(key, bool):
                fallback.append((key, entry))
                if entry['size'] >= required:
                    candidates.append((key, entry))
        pool = candidates if candidates else fallback
        if not pool:
            return None
        chosen_key, chosen_entry = pool[0]
        chosen_score = self._score(chosen_entry)
        for key, entry in pool[1:]:
            score = self._score(entry)
            if score < chosen_score or (score == chosen_score and entry['last'] < chosen_entry['last']):
                chosen_key, chosen_entry, chosen_score = key, entry, score
        return chosen_key

    def access(self, key, size, now):
        self.tick += 1
        try:
            amount = int(size)
        except Exception:
            amount = 0
        amount = max(0, amount)
        self.window += 1
        observed_frequency = self._observe(key)

        if key in self.resident:
            entry = self.resident[key]
            self.used += amount - entry['size']
            entry['size'] = amount
            entry['last'] = self.tick
            entry['freq'] = min(255, entry['freq'] + 1)
            if self.window >= 64:
                self.miss_pressure = self.window_misses / float(self.window)
                self.window = 0
                self.window_misses = 0
            return None

        self.window_misses += 1
        ghost_record = self.ghost.pop(key, None)
        ghost_bonus = 0
        if ghost_record is not None:
            ghost_bonus = min(8, 1 + ghost_record[1] // 2)

        if self.window >= 64:
            self.miss_pressure = self.window_misses / float(self.window)
            self.window = 0
            self.window_misses = 0

        if self.capacity <= 0 or amount > self.capacity:
            return None

        required = self.used + amount - self.capacity
        if required > 0:
            victim = self._victim(required)
            if victim is None:
                return None
            evicted = self.resident.pop(victim)
            self.used -= evicted['size']
            self._remember_ghost(victim, evicted)
            if self.used + amount > self.capacity:
                return victim
            eviction = victim
        else:
            eviction = None

        self.resident[key] = {
            'size': amount,
            'last': self.tick,
            'freq': max(1, observed_frequency),
            'ghost': ghost_bonus
        }
        self.used += amount
        return eviction
