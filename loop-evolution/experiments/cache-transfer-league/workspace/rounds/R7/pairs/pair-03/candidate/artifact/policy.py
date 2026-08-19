from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        try:
            capacity = int(capacity_bytes)
        except (TypeError, ValueError):
            capacity = 0
        self.capacity_bytes = max(0, capacity)
        self.entries = {}
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0
        self._tick = 0
        self._epoch = 0

    def _age(self, meta):
        delta = self._epoch - meta[4]
        if delta > 0:
            if delta >= 30:
                meta[2] = 1
            else:
                meta[2] = max(1, (meta[2] + (1 << delta) - 1) >> delta)
            meta[4] = self._epoch

    def _protected_limit(self):
        if self.capacity_bytes <= 0:
            return 0
        return max(1, (self.capacity_bytes * 3) // 4)

    def _rebalance(self):
        limit = self._protected_limit()
        while self.protected and self.protected_bytes > limit:
            old_key = next(iter(self.protected))
            self.protected.pop(old_key, None)
            meta = self.entries.get(old_key)
            if meta is None:
                continue
            meta[1] = False
            self.protected_bytes -= meta[0]
            self.probation[old_key] = None

    def _retire_stale_protected(self):
        for old_key in tuple(self.protected):
            meta = self.entries.get(old_key)
            if meta is None:
                self.protected.pop(old_key, None)
                continue
            if self._tick - meta[3] > 256:
                self.protected.pop(old_key, None)
                meta[1] = False
                self.protected_bytes -= meta[0]
                self.probation[old_key] = None

    def _score(self, meta):
        self._age(meta)
        age = self._tick - meta[3]
        if age < 0:
            age = 0
        recency = max(1, 4096 // (age + 1))
        return (meta[2] * 16384 + recency) * max(1, meta[0])

    def _pick_victim(self):
        order = self.probation if self.probation else self.protected
        best_key = None
        best_score = None
        for candidate in order:
            meta = self.entries.get(candidate)
            if meta is None:
                continue
            score = self._score(meta)
            if best_score is None or score < best_score:
                best_key = candidate
                best_score = score
        return best_key

    def _remove(self, key):
        meta = self.entries.pop(key, None)
        if meta is None:
            return
        if meta[1]:
            self.protected.pop(key, None)
            self.protected_bytes -= meta[0]
        else:
            self.probation.pop(key, None)
        self.used_bytes -= meta[0]

    def access(self, key: int, size: int, now: int) -> list[int]:
        self._tick += 1
        self._epoch = self._tick >> 8
        meta = self.entries.get(key)

        if meta is not None:
            self._age(meta)
            meta[2] = min(65535, meta[2] + 1)
            meta[3] = self._tick
            if meta[1]:
                self.protected.pop(key, None)
                self.protected[key] = None
            else:
                self.probation.pop(key, None)
                if meta[2] >= 2:
                    meta[1] = True
                    self.protected[key] = None
                    self.protected_bytes += meta[0]
                    self._rebalance()
                else:
                    self.probation[key] = None
            return []

        self._retire_stale_protected()
        try:
            requested = int(size)
        except (TypeError, ValueError):
            requested = 0
        requested = max(0, requested)

        if self.capacity_bytes == 0 or requested > self.capacity_bytes:
            return []

        evicted = []
        while self.used_bytes + requested > self.capacity_bytes:
            victim = self._pick_victim()
            if victim is None:
                return evicted
            self._remove(victim)
            evicted.append(victim)

        self.entries[key] = [requested, False, 1, self._tick, self._epoch]
        self.probation[key] = None
        self.used_bytes += requested
        return evicted
