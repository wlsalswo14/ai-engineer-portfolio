from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.entries = {}
        self.used_bytes = 0
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.reuse_interval = 2
        self.expiry = 8

    def _learn_gap(self, gap):
        if gap > 0:
            self.reuse_interval = max(1, (self.reuse_interval * 7 + gap) // 8)
            self.expiry = max(8, min(64, self.reuse_interval * 4))

    def _remove(self, key, evicted):
        record = self.entries.pop(key, None)
        if record is None:
            return
        size = record['size']
        if record['segment'] == 0:
            self.probation.pop(key, None)
            self.probation_bytes -= size
        else:
            self.protected.pop(key, None)
            self.protected_bytes -= size
        self.used_bytes -= size
        evicted.append(key)

    def _demote(self, key):
        record = self.entries.get(key)
        if record is None or record['segment'] != 1:
            return
        size = record['size']
        self.protected.pop(key, None)
        self.protected_bytes -= size
        record['segment'] = 0
        record['hits'] = 0
        self.probation[key] = None
        self.probation_bytes += size

    def _trim_probation(self, evicted, keep=None):
        limit = max(1, self.capacity_bytes // 4) if self.capacity_bytes else 0
        while self.probation_bytes > limit:
            victim = None
            for candidate in self.probation:
                if candidate != keep:
                    victim = candidate
                    break
            if victim is None:
                break
            self._remove(victim, evicted)

    def _expire_protected(self, now, evicted, keep=None):
        for key in list(self.protected):
            if key == keep:
                continue
            record = self.entries.get(key)
            if record is not None and now - record['last'] > self.expiry:
                self._demote(key)
                self._trim_probation(evicted, keep)

    def _enforce_protected(self, evicted, keep=None):
        target = max(1, (self.capacity_bytes * 3) // 4) if self.capacity_bytes else 0
        while self.protected_bytes > target:
            victim = None
            for candidate in self.protected:
                if candidate != keep:
                    victim = candidate
                    break
            if victim is None:
                break
            self._demote(victim)
            self._trim_probation(evicted, keep)

    def _promote(self, key, evicted):
        record = self.entries.get(key)
        if record is None or record['segment'] != 0:
            return
        size = record['size']
        self.probation.pop(key, None)
        self.probation_bytes -= size
        record['segment'] = 1
        self.protected[key] = None
        self.protected_bytes += size
        self._enforce_protected(evicted, key)

    def access(self, key: int, size: int, now: int) -> list[int]:
        size = max(0, int(size))
        evicted = []
        self._expire_protected(now, evicted, key)
        record = self.entries.get(key)

        if record is not None:
            gap = now - record['last']
            if record['segment'] == 1:
                if gap > self.expiry:
                    self._demote(key)
                    self._learn_gap(gap)
                    record['last'] = now
                    record['hits'] = 1
                    self.probation.move_to_end(key)
                    self._trim_probation(evicted, key)
                else:
                    self._learn_gap(gap)
                    record['last'] = now
                    self.protected.move_to_end(key)
                return evicted

            if gap > self.expiry:
                record['hits'] = 1
            else:
                record['hits'] += 1
            self._learn_gap(gap)
            record['last'] = now
            self.probation.move_to_end(key)
            if record['hits'] >= 2:
                self._promote(key, evicted)
            else:
                self._trim_probation(evicted, key)
            return evicted

        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            return evicted

        while self.used_bytes + size > self.capacity_bytes:
            victim = next(iter(self.probation), None)
            if victim is None:
                victim = next(iter(self.protected), None)
            if victim is None:
                break
            self._remove(victim, evicted)

        self.entries[key] = {
            'size': size,
            'segment': 0,
            'last': now,
            'hits': 1,
        }
        self.probation[key] = None
        self.probation_bytes += size
        self.used_bytes += size
        self._trim_probation(evicted, key)
        return evicted
