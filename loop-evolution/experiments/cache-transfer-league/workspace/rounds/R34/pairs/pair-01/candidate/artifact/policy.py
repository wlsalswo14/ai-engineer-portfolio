from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.used = 0
        self.protected_bytes = 0
        self.target = int(self.capacity * 0.70)
        self.entries = {}
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost = OrderedDict()
        self.ghost_limit = 1024
        self.step = 0

    def _remember(self, key, segment):
        self.ghost.pop(key, None)
        self.ghost[key] = segment
        while len(self.ghost) > self.ghost_limit:
            self.ghost.popitem(last=False)

    def _remove(self, key):
        entry = self.entries.pop(key, None)
        if entry is None:
            return
        size, _, _, segment = entry
        self.used -= size
        if segment:
            self.protected.pop(key, None)
            self.protected_bytes -= size
        else:
            self.probation.pop(key, None)
        self._remember(key, segment)

    def _promote(self, key, entry):
        size = entry[0]
        self.probation.pop(key, None)
        self.protected[key] = None
        entry[3] = 1
        self.protected_bytes += size
        while self.protected_bytes > self.target and self.protected:
            old, _ = self.protected.popitem(last=False)
            old_entry = self.entries.get(old)
            if old_entry is None:
                continue
            old_entry[3] = 0
            self.protected_bytes -= old_entry[0]
            self.probation[old] = None

    def _victim(self):
        for pool in (self.probation, self.protected):
            chosen = None
            chosen_score = None
            for key in pool:
                entry = self.entries.get(key)
                if entry is None:
                    continue
                age = max(0, self.step - entry[2])
                size = max(1, entry[0])
                score = (1.0 + 2.0 * min(entry[1], 32)) / (size * (1.0 + age / 32.0))
                if entry[3]:
                    score *= 1.25
                if chosen_score is None or score < chosen_score:
                    chosen = key
                    chosen_score = score
            if chosen is not None:
                return chosen
        return None

    def _adjust_target(self, segment):
        if self.capacity <= 0:
            return
        delta = max(1, self.capacity // 16)
        if segment:
            self.target = min(self.capacity, self.target + delta)
        else:
            self.target = max(0, self.target - delta)

    def access(self, key: int, size: int, now: int) -> list[int]:
        self.step += 1
        requested = max(0, int(size))
        entry = self.entries.get(key)
        if entry is not None:
            entry[1] += 1
            entry[2] = self.step
            if entry[3]:
                self.protected.move_to_end(key)
            else:
                self._promote(key, entry)
            return []

        if requested > self.capacity:
            self.ghost.pop(key, None)
            return []

        old_segment = self.ghost.pop(key, None)
        if old_segment is not None:
            self._adjust_target(old_segment)

        evicted = []
        while self.used + requested > self.capacity:
            victim = self._victim()
            if victim is None:
                break
            self._remove(victim)
            evicted.append(victim)

        if self.used + requested > self.capacity:
            return evicted

        self.entries[key] = [requested, 0, self.step, 0]
        self.probation[key] = None
        self.used += requested
        return evicted
