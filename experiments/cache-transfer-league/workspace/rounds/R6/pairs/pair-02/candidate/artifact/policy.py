from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.used_bytes = 0
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.entries = {}
        self.history = OrderedDict()
        self.ticks = 0

    def _remember(self, key):
        value = min(255, self.history.get(key, 0) + 1)
        self.history.pop(key, None)
        self.history[key] = value
        while len(self.history) > 8192:
            self.history.popitem(last=False)

    def _age(self):
        if self.ticks % 512 != 0:
            return
        for record in self.entries.values():
            record[1] = max(1, (record[1] + 1) // 2)
        for key in list(self.history):
            value = max(1, (self.history[key] + 1) // 2)
            if value == 1 and key not in self.entries:
                del self.history[key]
            else:
                self.history[key] = value

    def _protected_target(self):
        return max(1, (self.capacity_bytes * 3) // 5)

    def _demote(self):
        protected_bytes = sum(self.entries[key][0] for key in self.protected)
        while self.protected and protected_bytes > self._protected_target():
            key, _ = self.protected.popitem(last=False)
            self.probation[key] = None
            protected_bytes -= self.entries[key][0]

    def _victim(self):
        if self.probation:
            container = self.probation
            is_protected = False
        elif self.protected:
            container = self.protected
            is_protected = True
        else:
            return None, False

        best_key = None
        best_score = None
        scanned = 0
        for key in container:
            record = self.entries[key]
            age = max(0, self.ticks - record[2])
            score = ((record[1] + 1) * 4096) // max(1, record[0])
            score += 4096 // (age + 1)
            if best_score is None or score < best_score:
                best_key = key
                best_score = score
            scanned += 1
            if scanned >= 32:
                break
        return best_key, is_protected

    def access(self, key: int, size: int, now: int) -> list[int]:
        self.ticks += 1
        self._remember(key)
        self._age()

        if key in self.entries:
            record = self.entries[key]
            record[1] = min(255, record[1] + 1)
            record[2] = self.ticks
            if key in self.probation:
                self.probation.pop(key)
                self.protected[key] = None
                self._demote()
            else:
                self.protected.move_to_end(key)
            return []

        size = max(0, int(size))
        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        evicted = []
        remaining = self.used_bytes + size - self.capacity_bytes
        while remaining > 0:
            victim, is_protected = self._victim()
            if victim is None:
                return evicted
            if is_protected:
                self.protected.pop(victim)
            else:
                self.probation.pop(victim)
            record = self.entries.pop(victim)
            self.used_bytes -= record[0]
            remaining -= record[0]
            evicted.append(victim)

        frequency = max(1, self.history.get(key, 1))
        self.entries[key] = [size, min(255, frequency), self.ticks]
        self.probation[key] = None
        self.used_bytes += size
        self._demote()
        return evicted
