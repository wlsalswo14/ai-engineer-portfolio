from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0
        self.protected_fraction = 0.55
        self.clock = 0
        self.requests = 0
        self.hit_ema = 0.0
        self.max_ghost = max(64, min(2048, self.capacity_bytes // 64 + 64))

    def _observe(self, hit: bool, ghost_hit: bool = False):
        self.requests += 1
        self.hit_ema = self.hit_ema * 0.97 + (1.0 if hit else 0.0) * 0.03
        if ghost_hit:
            self.protected_fraction = min(0.72, self.protected_fraction + 0.08)
        elif hit:
            self.protected_fraction = min(0.72, self.protected_fraction + 0.006)
        else:
            self.protected_fraction = max(0.38, self.protected_fraction - 0.002)

    def _demote_protected(self):
        target = int(self.capacity_bytes * self.protected_fraction)
        while self.protected and self.protected_bytes > target:
            key, record = self.protected.popitem(last=False)
            self.protected_bytes -= record[0]
            self.probation[key] = record

    def _remember(self, key):
        self.ghost[key] = self.clock
        while len(self.ghost) > self.max_ghost:
            self.ghost.popitem(last=False)

    def _pick_victim(self, bucket):
        best_key = None
        best_score = None
        for position, (candidate, record) in enumerate(bucket.items()):
            if position >= 16:
                break
            size, frequency, last_seen = record
            age = max(0, self.clock - last_seen)
            score = (frequency + 1.0) * (1.0 + 1.0 / (age + 1.0)) / max(1.0, size) ** 0.5
            if best_score is None or score < best_score:
                best_key = candidate
                best_score = score
        return best_key

    def _remove(self, key):
        if key in self.probation:
            size = self.probation.pop(key)[0]
            self.used_bytes -= size
            return size
        if key in self.protected:
            size = self.protected.pop(key)[0]
            self.protected_bytes -= size
            self.used_bytes -= size
            return size
        return 0

    def access(self, key: int, size: int, now: int) -> list[int]:
        self.clock += 1
        if key in self.protected:
            record = self.protected.pop(key)
            record[1] += 1
            record[2] = self.clock
            self.protected[key] = record
            self._observe(True)
            return []

        if key in self.probation:
            record = self.probation.pop(key)
            record[1] += 1
            record[2] = self.clock
            self.protected[key] = record
            self.protected_bytes += record[0]
            self._observe(True)
            self._demote_protected()
            return []

        requested_size = max(0, size)
        ghost_hit = key in self.ghost
        if ghost_hit:
            self.ghost.pop(key, None)
        self._observe(False, ghost_hit)

        if self.capacity_bytes == 0 or requested_size > self.capacity_bytes:
            return []

        evicted = []
        while self.used_bytes + requested_size > self.capacity_bytes:
            victim = self._pick_victim(self.probation)
            if victim is None:
                victim = self._pick_victim(self.protected)
            if victim is None:
                break
            self._remove(victim)
            self._remember(victim)
            evicted.append(victim)

        if self.used_bytes + requested_size > self.capacity_bytes:
            return evicted

        record = [requested_size, 1, self.clock]
        if ghost_hit:
            self.protected[key] = record
            self.protected_bytes += requested_size
        else:
            self.probation[key] = record
        self.used_bytes += requested_size
        self._demote_protected()
        return evicted
