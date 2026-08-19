from collections import OrderedDict
import math


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.residents = OrderedDict()
        self.history = OrderedDict()
        self.used_bytes = 0
        self.clock = 0
        self.last_now = None
        self.requests = 0

    def _advance(self, now):
        observed = int(now)
        if self.last_now is None:
            self.clock = 1
        elif observed > self.last_now:
            self.clock += min(observed - self.last_now, 1024)
        else:
            self.clock += 1
        if self.last_now is None or observed > self.last_now:
            self.last_now = observed

    def _age_statistics(self):
        if self.requests % 64:
            return
        for entry in self.residents.values():
            entry[2] = max(1, entry[2] // 2)
        for key in list(self.history):
            count = self.history[key] // 2
            if count:
                self.history[key] = count
            else:
                del self.history[key]

    def _record(self, key):
        count = self.history.get(key, 0) + 1
        if key in self.history:
            del self.history[key]
        self.history[key] = count
        while len(self.history) > 4096:
            self.history.popitem(last=False)
        return count

    def _value(self, entry):
        size, last_seen, frequency = entry
        age = max(0, self.clock - last_seen)
        freshness = 1.0 / (1.0 + age)
        return (1.0 + math.log1p(frequency)) * (0.5 + 0.5 * freshness) / math.sqrt(size)

    def _admit(self, key, size, frequency):
        self.residents[key] = [size, self.clock, max(1, frequency)]
        self.used_bytes += size

    def access(self, key: int, size: int, now: int) -> list[int]:
        size = int(size)
        if size <= 0:
            return []

        self._advance(now)
        self.requests += 1
        self._age_statistics()
        frequency = self._record(key)

        if key in self.residents:
            entry = self.residents.pop(key)
            self.used_bytes += size - entry[0]
            entry[0] = size
            entry[1] = self.clock
            entry[2] = min(1000000, entry[2] + 1)
            if size > self.capacity_bytes:
                self.used_bytes -= size
                return [key]
            self.residents[key] = entry
            evicted = []
            while self.used_bytes > self.capacity_bytes:
                victim = min(
                    self.residents,
                    key=lambda candidate: (
                        self._value(self.residents[candidate]),
                        self.residents[candidate][1],
                        candidate,
                    ),
                )
                victim_entry = self.residents.pop(victim)
                self.used_bytes -= victim_entry[0]
                evicted.append(victim)
            return evicted

        if size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        required = self.used_bytes + size - self.capacity_bytes
        if required <= 0:
            self._admit(key, size, frequency)
            return []

        if frequency < 2:
            return []

        candidate_value = (1.0 + math.log1p(frequency)) / math.sqrt(size)
        victims = []
        freed = 0
        ordered = sorted(
            self.residents.items(),
            key=lambda pair: (self._value(pair[1]), pair[1][1], pair[0]),
        )
        for victim, entry in ordered:
            if candidate_value <= self._value(entry):
                return []
            victims.append(victim)
            freed += entry[0]
            if freed >= required:
                break

        if freed < required:
            return []

        evicted = []
        for victim in victims:
            entry = self.residents.pop(victim)
            self.used_bytes -= entry[0]
            evicted.append(victim)
        self._admit(key, size, frequency)
        return evicted
