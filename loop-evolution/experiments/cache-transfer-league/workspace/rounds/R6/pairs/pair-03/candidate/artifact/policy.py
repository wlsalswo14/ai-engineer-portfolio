from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.entries = {}
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.protected_bytes = 0
        self.used_bytes = 0
        self.frequency = OrderedDict()
        self.requests = 0

    def _touch(self, key):
        self.frequency[key] = min(255, self.frequency.get(key, 0) + 1)
        self.frequency.move_to_end(key)
        if len(self.frequency) > 16384:
            self.frequency.popitem(last=False)

    def _age(self):
        for key in list(self.frequency):
            value = self.frequency[key] // 2
            if value:
                self.frequency[key] = value
            else:
                del self.frequency[key]

    def _score(self, key, size):
        return self.frequency.get(key, 1) * 4096 // max(1, size)

    def _rebalance_protected(self):
        target = (self.capacity_bytes * 3) // 4
        while self.protected and self.protected_bytes > target:
            key, size = self.protected.popitem(last=False)
            self.entries[key][1] = 0
            self.protected_bytes -= size
            self.probation[key] = size

    def _pick_victim(self, pool, excluded):
        chosen = None
        chosen_score = None
        for key in pool:
            if key in excluded:
                continue
            score = self._score(key, self.entries[key][0])
            if chosen is None or score < chosen_score:
                chosen = key
                chosen_score = score
        return chosen

    def _remove(self, key):
        size, protected = self.entries.pop(key)
        if protected:
            self.protected.pop(key, None)
            self.protected_bytes -= size
        else:
            self.probation.pop(key, None)
        self.used_bytes -= size

    def access(self, key: int, size: int, now: int) -> list[int]:
        del now
        size = int(size)
        self.requests += 1
        self._touch(key)
        if self.requests % 2048 == 0:
            self._age()

        record = self.entries.get(key)
        if record is not None:
            if record[1]:
                self.protected.move_to_end(key)
            else:
                self.probation.pop(key, None)
                record[1] = 1
                self.protected[key] = record[0]
                self.protected_bytes += record[0]
                self._rebalance_protected()
            return []

        if self.capacity_bytes == 0 or size <= 0 or size > self.capacity_bytes:
            return []

        self._rebalance_protected()
        required = self.used_bytes + size - self.capacity_bytes
        victims = []
        excluded = set()
        freed = 0
        while freed < required:
            victim = self._pick_victim(self.probation, excluded)
            if victim is None:
                victim = self._pick_victim(self.protected, excluded)
            if victim is None:
                return []
            excluded.add(victim)
            victims.append(victim)
            freed += self.entries[victim][0]

        candidate_score = self._score(key, size)
        for victim in victims:
            victim_size = self.entries[victim][0]
            if self._score(victim, victim_size) > candidate_score:
                return []

        evicted = []
        for victim in victims:
            self._remove(victim)
            evicted.append(victim)

        self.entries[key] = [size, 0]
        self.probation[key] = size
        self.used_bytes += size
        return evicted
