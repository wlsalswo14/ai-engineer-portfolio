class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.used_bytes = 0
        self.clock = 0
        self.items = {}
        self.observations = {}

    def _utility(self, entry):
        size, frequency, last = entry
        age = self.clock - last
        return frequency * 1000000000 // (size + 1) - age * 4096

    def _decay(self):
        for key, count in list(self.observations.items()):
            reduced = count // 2
            if reduced > 0:
                self.observations[key] = reduced
            elif key in self.items:
                self.observations[key] = 1
            else:
                del self.observations[key]
        for key, entry in self.items.items():
            entry[1] = self.observations.get(key, 1)

    def access(self, key: int, size: int, now: int) -> list[int]:
        self.clock += 1
        if self.clock % 512 == 0:
            self._decay()

        if size < 0:
            size = 0

        frequency = self.observations.get(key, 0) + 1
        self.observations[key] = frequency

        entry = self.items.get(key)
        if entry is not None:
            entry[1] = frequency
            entry[2] = self.clock
            return []

        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        if self.used_bytes + size <= self.capacity_bytes:
            self.items[key] = [size, frequency, self.clock]
            self.used_bytes += size
            return []

        incoming = [size, frequency, self.clock]
        incoming_utility = self._utility(incoming)
        candidates = sorted(
            self.items.items(),
            key=lambda pair: (self._utility(pair[1]), pair[1][2])
        )

        required = self.used_bytes + size - self.capacity_bytes
        selected = []
        freed = 0
        for old_key, old_entry in candidates:
            if self._utility(old_entry) >= incoming_utility:
                return []
            selected.append(old_key)
            freed += old_entry[0]
            if freed >= required:
                break

        if freed < required:
            return []

        evicted = []
        for old_key in selected:
            old_entry = self.items.pop(old_key)
            self.used_bytes -= old_entry[0]
            evicted.append(old_key)

        self.items[key] = incoming
        self.used_bytes += size
        return evicted
