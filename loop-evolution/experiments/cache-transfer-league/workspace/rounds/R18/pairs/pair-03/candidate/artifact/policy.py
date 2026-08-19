from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.protected_bytes = 0
        self.used_bytes = 0
        self.meta = {}
        self.window = 32.0
        self.last_now = None
        self.touches = 0

    def _observe(self, key, now):
        if self.last_now is not None:
            gap = max(1, now - self.last_now)
            self.window = min(4096.0, max(4.0, self.window * 0.875 + gap * 0.125))
        self.last_now = now
        record = self.meta.get(key)
        if record is None:
            heat = 1.0
        else:
            elapsed = max(0, now - record[1])
            heat = record[0] / (1.0 + elapsed / self.window) + 1.0
        self.meta[key] = (min(1000000.0, heat), now)
        self.touches += 1
        if self.touches % 257 == 0 and len(self.meta) > 4096:
            resident = set(self.probation) | set(self.protected)
            stale = [(value[1], item) for item, value in self.meta.items() if item not in resident]
            stale.sort()
            for _, item in stale[:len(self.meta) - 4096]:
                self.meta.pop(item, None)

    def _utility(self, key, size, now, protected=False):
        record = self.meta.get(key)
        if record is None:
            return 0.0
        elapsed = max(0, now - record[1])
        heat = record[0] / (1.0 + elapsed / self.window)
        ratio = size / float(max(1, self.capacity_bytes))
        segment_bonus = 1.14 if protected else 1.0
        return segment_bonus * heat * (0.55 + 0.45 / (1.0 + ratio))

    def _demote_protected(self):
        target = self.capacity_bytes * 0.7
        while self.protected and self.protected_bytes > target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size

    def access(self, key: int, size: int, now: int) -> list[int]:
        now = int(now)
        item_size = max(0, int(size))
        self._observe(key, now)

        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            self._demote_protected()
            return []

        if self.capacity_bytes == 0 or item_size > self.capacity_bytes:
            return []

        needed = self.used_bytes + item_size - self.capacity_bytes
        selected = []
        if needed > 0:
            candidates = []
            for victim, victim_size in self.probation.items():
                candidates.append((self._utility(victim, victim_size, now), victim, victim_size))
            for victim, victim_size in self.protected.items():
                candidates.append((self._utility(victim, victim_size, now, True), victim, victim_size))
            candidates.sort(key=lambda entry: (entry[0], entry[1]))
            freed = 0
            for entry in candidates:
                selected.append(entry)
                freed += entry[2]
                if freed >= needed:
                    break
            if freed < needed:
                return []
            candidate_score = self._utility(key, item_size, now)
            if candidate_score <= max(entry[0] for entry in selected):
                return []

        evicted = []
        for _, victim, victim_size in selected:
            if victim in self.probation:
                del self.probation[victim]
            else:
                del self.protected[victim]
                self.protected_bytes -= victim_size
            self.used_bytes -= victim_size
            evicted.append(victim)

        self.probation[key] = item_size
        self.used_bytes += item_size
        return evicted
