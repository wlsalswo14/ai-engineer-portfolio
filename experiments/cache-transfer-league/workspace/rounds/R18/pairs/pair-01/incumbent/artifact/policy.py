from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0
        self.protected_limit = (self.capacity_bytes * 3) // 5
        self._width = 1024
        self._mask = self._width - 1
        self._sketch = [bytearray(self._width) for _ in range(4)]
        self._salts = (0x9E3779B1, 0x85EBCA77, 0xC2B2AE3D, 0x27D4EB2F)
        self._updates = 0
        self._decay_interval = self._width * 2

    def _slot(self, key, salt):
        x = (key ^ salt) & 0xFFFFFFFFFFFFFFFF
        x ^= x >> 30
        x = (x * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        x ^= x >> 27
        x = (x * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
        x ^= x >> 31
        return x & self._mask

    def _frequency(self, key):
        value = 255
        for row, salt in zip(self._sketch, self._salts):
            value = min(value, row[self._slot(key, salt)])
        return value

    def _record(self, key):
        for row, salt in zip(self._sketch, self._salts):
            slot = self._slot(key, salt)
            if row[slot] < 255:
                row[slot] += 1
        self._updates += 1
        if self._updates >= self._decay_interval:
            for row in self._sketch:
                for index in range(self._width):
                    row[index] >>= 1
            self._updates = 0

    def _demote_protected(self):
        while self.protected and self.protected_bytes > self.protected_limit:
            old_key, old_size = self.protected.popitem(last=False)
            self.protected_bytes -= old_size
            self.probation[old_key] = old_size

    def _planned_victims(self, size, candidate_frequency):
        if self.used_bytes + size <= self.capacity_bytes:
            return []
        victims = []
        freed = 0
        for segment in (self.probation, self.protected):
            for victim_key, victim_size in segment.items():
                if self.used_bytes - freed + size <= self.capacity_bytes:
                    return victims
                if candidate_frequency <= self._frequency(victim_key):
                    return None
                victims.append(victim_key)
                freed += victim_size
        return victims if self.used_bytes - freed + size <= self.capacity_bytes else None

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            self._record(key)
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            self._demote_protected()
            self._record(key)
            return []

        self._record(key)
        size = max(0, int(size))
        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        victims = self._planned_victims(size, self._frequency(key))
        if victims is None:
            return []

        evicted = []
        for victim_key in victims:
            if victim_key in self.probation:
                victim_size = self.probation.pop(victim_key)
            else:
                victim_size = self.protected.pop(victim_key)
                self.protected_bytes -= victim_size
            self.used_bytes -= victim_size
            evicted.append(victim_key)

        self.probation[key] = size
        self.used_bytes += size
        return evicted
