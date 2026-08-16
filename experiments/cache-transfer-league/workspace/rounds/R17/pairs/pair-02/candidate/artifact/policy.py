class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.entries = {}
        self.history = {}
        self.used_bytes = 0
        self._tick = 0

    def _age(self):
        for key, (size, last, frequency) in tuple(self.entries.items()):
            self.entries[key] = (size, last, max(1, frequency // 2))
        for key, (count, last) in tuple(self.history.items()):
            count = max(1, count // 2)
            if key not in self.entries and self._tick - last > 4096 and count <= 1:
                del self.history[key]
            else:
                self.history[key] = (count, last)

    def _score(self, record):
        size, last, frequency = record
        age = min(self._tick - last, 768)
        size_penalty = min(256, (size * 256) // max(1, self.capacity_bytes))
        return frequency * 1024 - age - size_penalty

    def access(self, key: int, size: int, now: int) -> list[int]:
        self._tick += 1
        if self._tick % 512 == 0:
            self._age()

        history_record = self.history.get(key)
        previous_count = history_record[0] if history_record is not None else 0
        self.history[key] = (min(previous_count + 1, 1000000), self._tick)

        current = self.entries.get(key)
        if current is not None:
            stored_size, _, frequency = current
            self.entries[key] = (stored_size, self._tick, min(frequency + 1, 1000000))
            return []

        if size < 0:
            size = 0
        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        candidate_frequency = min(previous_count + 1, 1000000)
        candidate_penalty = min(256, (size * 256) // max(1, self.capacity_bytes))
        candidate_score = candidate_frequency * 1024 - candidate_penalty
        victims = []
        remaining = self.used_bytes

        order = sorted(
            self.entries,
            key=lambda item: (self._score(self.entries[item]), self.entries[item][1], item),
        )
        for victim in order:
            if remaining + size <= self.capacity_bytes:
                break
            if self._score(self.entries[victim]) >= candidate_score:
                return []
            victims.append(victim)
            remaining -= self.entries[victim][0]

        if remaining + size > self.capacity_bytes:
            return []

        for victim in victims:
            self.used_bytes -= self.entries[victim][0]
            del self.entries[victim]

        self.entries[key] = (size, self._tick, candidate_frequency)
        self.used_bytes += size
        return victims
