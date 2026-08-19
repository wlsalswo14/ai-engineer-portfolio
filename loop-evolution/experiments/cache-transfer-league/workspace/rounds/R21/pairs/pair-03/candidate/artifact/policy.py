from collections import OrderedDict
from math import isqrt


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.entries = {}
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0
        self.protected_target = self.capacity_bytes // 2
        self.min_protected = (max(1, self.capacity_bytes // 8)
                              if self.capacity_bytes else 0)
        self.max_protected = max(self.min_protected,
                                 (7 * self.capacity_bytes) // 8)
        self.adjustment = max(1, self.capacity_bytes // 16)
        self.ghost_limit = 2048
        self.tick = 0
        self.miss_streak = 0

    def _remember(self, key):
        self.ghost.pop(key, None)
        self.ghost[key] = None
        while len(self.ghost) > self.ghost_limit:
            self.ghost.popitem(last=False)

    def _demote_oldest_protected(self):
        if not self.protected:
            return False
        old_key, _ = self.protected.popitem(last=False)
        entry = self.entries[old_key]
        self.protected_bytes -= entry[0]
        entry[3] = 0
        self.probation[old_key] = None
        return True

    def _rebalance_protected(self):
        while (self.protected and
               self.protected_bytes > self.protected_target):
            self._demote_oldest_protected()

    def _victim(self):
        if not self.probation:
            return None
        choice = None
        choice_score = None
        for rank, candidate in enumerate(self.probation):
            size, hits, _, _ = self.entries[candidate]
            density = ((hits + 1) * 4096) // max(1, isqrt(max(1, size)))
            score = density + rank
            if choice_score is None or score < choice_score:
                choice = candidate
                choice_score = score
        return choice

    def _remove(self, key):
        entry = self.entries.pop(key)
        self.probation.pop(key, None)
        self.protected.pop(key, None)
        self.used_bytes -= entry[0]
        if entry[3]:
            self.protected_bytes -= entry[0]
        self._remember(key)
        return entry[0]

    def access(self, key: int, size: int, now: int) -> list[int]:
        self.tick += 1
        entry = self.entries.get(key)
        if entry is not None:
            entry[2] = self.tick
            entry[1] = min(255, entry[1] + 1)
            self.miss_streak = 0
            if entry[3]:
                self.protected.pop(key, None)
                self.protected[key] = None
            else:
                self.probation.pop(key, None)
                self.protected[key] = None
                entry[3] = 1
                self.protected_bytes += entry[0]
                self._rebalance_protected()
            return []

        incoming = max(0, int(size))
        if self.capacity_bytes == 0 or incoming > self.capacity_bytes:
            return []

        was_ghost = key in self.ghost
        self.ghost.pop(key, None)
        if was_ghost:
            self.miss_streak = 0
            self.protected_target = min(
                self.max_protected,
                self.protected_target + self.adjustment,
            )
        else:
            self.miss_streak += 1
            if self.miss_streak >= 8 and self.miss_streak % 8 == 0:
                self.protected_target = max(
                    self.min_protected,
                    self.protected_target - self.adjustment,
                )
        self._rebalance_protected()

        evicted = []
        while self.used_bytes + incoming > self.capacity_bytes:
            victim = self._victim()
            if victim is None:
                if not self._demote_oldest_protected():
                    break
                victim = self._victim()
            if victim is None:
                break
            self._remove(victim)
            evicted.append(victim)

        self.entries[key] = [incoming, 0, self.tick, 0]
        self.probation[key] = None
        self.used_bytes += incoming
        self._rebalance_protected()
        return evicted
