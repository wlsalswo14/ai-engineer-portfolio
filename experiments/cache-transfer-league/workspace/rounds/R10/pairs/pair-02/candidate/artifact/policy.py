from collections import OrderedDict
import math


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.cache = {}
        self.pending = OrderedDict()
        self.tick = 0
        self.half_life = 64.0
        self.pending_limit = 4096

    def _decayed(self, evidence, last_tick):
        age = self.tick - last_tick
        if age <= 0:
            return evidence
        return evidence * math.exp(-age / self.half_life)

    def _priority(self, record):
        size, evidence, last_tick = record
        current = self._decayed(evidence, last_tick)
        return current / math.sqrt(max(1, size))

    def _worst_key(self):
        worst = None
        worst_value = None
        for key, record in self.cache.items():
            value = self._priority(record)
            if worst_value is None or value < worst_value:
                worst = key
                worst_value = value
        return worst

    def access(self, key: int, size: int, now: int) -> list[int]:
        self.tick += 1

        if key in self.cache:
            stored_size, evidence, last_tick = self.cache.pop(key)
            evidence = self._decayed(evidence, last_tick) + 1.0
            self.cache[key] = (stored_size, evidence, self.tick)
            return []

        if not isinstance(size, int) or size <= 0 or size > self.capacity_bytes:
            self.pending.pop(key, None)
            return []

        prior = self.pending.pop(key, None)
        if prior is None:
            self.pending[key] = (size, 1)
            if len(self.pending) > self.pending_limit:
                self.pending.popitem(last=False)
            return []

        candidate_size, count = prior
        candidate_size = size
        count += 1
        if count < 2:
            self.pending[key] = (candidate_size, count)
            return []

        candidate = (candidate_size, float(count), self.tick)
        evicted = []
        needed = sum(record[0] for record in self.cache.values()) + candidate_size - self.capacity_bytes

        if needed > 0:
            while needed > 0 and self.cache:
                old_key = self._worst_key()
                old_record = self.cache[old_key]
                if self._priority(candidate) <= self._priority(old_record):
                    return []
                self.cache.pop(old_key)
                needed -= old_record[0]
                evicted.append(old_key)

            if needed > 0:
                return []

        self.cache[key] = candidate
        return evicted
