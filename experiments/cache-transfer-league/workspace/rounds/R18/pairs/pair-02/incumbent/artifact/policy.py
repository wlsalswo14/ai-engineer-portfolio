from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.used_bytes = 0
        self._clock = 0
        self._frequency = {}

    def _priority(self, key, entry):
        return (self._frequency.get(key, 1), entry[1])

    def _demote_protected(self):
        target = self.capacity_bytes // 2
        protected_bytes = sum(entry[0] for entry in self.protected.values())
        while self.protected and protected_bytes > target:
            key, entry = self.protected.popitem(last=False)
            self.probation[key] = entry
            protected_bytes -= entry[0]

    def _victim_candidates(self):
        candidates = []
        for key, entry in self.probation.items():
            candidates.append((self._priority(key, entry), key, entry))
        for key, entry in self.protected.items():
            candidates.append((self._priority(key, entry), key, entry))
        candidates.sort(key=lambda item: item[0])
        return candidates

    def access(self, key: int, size: int, now: int) -> list[int]:
        self._clock += 1
        self._frequency[key] = self._frequency.get(key, 0) + 1

        if key in self.protected:
            stored_size, _ = self.protected.pop(key)
            self.protected[key] = (stored_size, self._clock)
            return []

        if key in self.probation:
            stored_size, _ = self.probation.pop(key)
            self.protected[key] = (stored_size, self._clock)
            self._demote_protected()
            return []

        if self.capacity_bytes == 0 or size <= 0 or size > self.capacity_bytes:
            return []

        candidate_priority = (self._frequency[key], self._clock)
        required = self.used_bytes + size - self.capacity_bytes
        victims = []
        reclaimed = 0

        for priority, victim_key, victim_entry in self._victim_candidates():
            if reclaimed >= required:
                break
            if candidate_priority <= priority:
                break
            victims.append((victim_key, victim_entry))
            reclaimed += victim_entry[0]

        if reclaimed < required:
            return []

        evicted = []
        for victim_key, victim_entry in victims:
            if victim_key in self.probation:
                del self.probation[victim_key]
            elif victim_key in self.protected:
                del self.protected[victim_key]
            else:
                continue
            self.used_bytes -= victim_entry[0]
            evicted.append(victim_key)

        self.probation[key] = (size, self._clock)
        self.used_bytes += size
        self._demote_protected()
        return evicted
