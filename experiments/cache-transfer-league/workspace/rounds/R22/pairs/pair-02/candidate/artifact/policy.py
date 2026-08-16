from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.window = OrderedDict()
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.window_bytes = 0
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.used_bytes = 0
        self.meta = {}
        self.ghost = OrderedDict()
        self.clock = 0
        self.window_percent = 20

    def _window_limit(self):
        if self.capacity_bytes == 0:
            return 0
        return min(self.capacity_bytes, max(1, self.capacity_bytes * self.window_percent // 100))

    def _decay(self):
        for record in self.meta.values():
            record[0] = max(1, record[0] // 2)
        for key, record in list(self.ghost.items()):
            self.ghost[key] = (max(1, record[0] // 2), record[1])

    def _touch(self, key):
        record = self.meta[key]
        record[0] = min(1048576, record[0] + 1)
        record[1] = self.clock

    def _score(self, key, size, bonus):
        count, last = self.meta.get(key, (1, self.clock))
        age = self.clock - last
        recent = max(0, 64 - age)
        return ((count * 64) + (recent * 4) + bonus) * 1024 // max(1, size)

    def _choose_victim(self, excluded):
        best_key = None
        best_score = None
        groups = ((0, self.window), (96, self.probation), (256, self.protected))
        for bonus, segment in groups:
            for key in list(segment.keys())[:32]:
                if key == excluded:
                    continue
                score = self._score(key, segment[key], bonus)
                if best_score is None or score < best_score:
                    best_key = key
                    best_score = score
        if best_key is not None:
            return best_key
        for segment in (self.window, self.probation, self.protected):
            for key in segment:
                if key != excluded:
                    return key
        return None

    def _remove(self, key):
        if key in self.window:
            size = self.window.pop(key)
            self.window_bytes -= size
            kind = 'w'
        elif key in self.probation:
            size = self.probation.pop(key)
            self.probation_bytes -= size
            kind = 'm'
        else:
            size = self.protected.pop(key)
            self.protected_bytes -= size
            kind = 'm'
        self.used_bytes -= size
        return kind, size

    def _remember(self, key, kind):
        record = self.meta.pop(key, None)
        count = 1 if record is None else record[0]
        self.ghost[key] = (count, kind)
        self.ghost.move_to_end(key)
        while len(self.ghost) > 4096:
            self.ghost.popitem(last=False)

    def _evict(self, key, evicted):
        kind, _ = self._remove(key)
        self._remember(key, kind)
        evicted.append(key)

    def _rebalance_protected(self):
        target = max(0, (self.capacity_bytes - self._window_limit()) * 4 // 5)
        while self.protected and self.protected_bytes > target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size
            self.probation_bytes += size

    def _promote(self, key, source):
        if source == 'w':
            size = self.window.pop(key)
            self.window_bytes -= size
        else:
            size = self.probation.pop(key)
            self.probation_bytes -= size
        self.protected[key] = size
        self.protected_bytes += size
        self._rebalance_protected()

    def _ghost_count(self, key):
        record = self.ghost.pop(key, None)
        if record is None:
            return 1
        if record[1] == 'w':
            self.window_percent = min(35, self.window_percent + 4)
        else:
            self.window_percent = max(8, self.window_percent - 4)
        return min(1048576, record[0] + 1)

    def access(self, key: int, size: int, now: int) -> list[int]:
        self.clock += 1
        if self.clock % 4096 == 0:
            self._decay()

        if key in self.window:
            self.window.move_to_end(key)
            self._touch(key)
            if self.meta[key][0] >= 2:
                self._promote(key, 'w')
            return []

        if key in self.probation:
            self.probation.move_to_end(key)
            self._touch(key)
            self._promote(key, 'm')
            return []

        if key in self.protected:
            self.protected.move_to_end(key)
            self._touch(key)
            return []

        item_size = max(0, size)
        if self.capacity_bytes == 0 or item_size > self.capacity_bytes:
            return []

        base_count = self._ghost_count(key)
        self.meta[key] = [base_count, self.clock]
        self.window[key] = item_size
        self.window_bytes += item_size
        self.used_bytes += item_size

        evicted = []
        while self.used_bytes > self.capacity_bytes:
            victim = self._choose_victim(key)
            if victim is None:
                break
            self._evict(victim, evicted)

        limit = self._window_limit()
        while self.window and self.window_bytes > limit:
            old_key, old_size = self.window.popitem(last=False)
            self.window_bytes -= old_size
            self.probation[old_key] = old_size
            self.probation_bytes += old_size

        self._rebalance_protected()
        return evicted
