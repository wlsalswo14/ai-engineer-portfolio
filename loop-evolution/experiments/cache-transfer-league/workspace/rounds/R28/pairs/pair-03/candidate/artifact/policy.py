from collections import OrderedDict
from math import isqrt


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.ghost_limit = 4096
        self.protected_target = self.capacity_bytes // 2
        self.used_bytes = 0
        self.protected_bytes = 0
        self.frequency = {}
        self.frequency_limit = 8192
        self.tick = 0
        self.decay_period = 4096

    def _record(self, key):
        self.tick += 1
        if self.tick % self.decay_period == 0:
            for old_key, count in tuple(self.frequency.items()):
                count >>= 1
                if count:
                    self.frequency[old_key] = count
                else:
                    del self.frequency[old_key]
        if key in self.frequency:
            self.frequency[key] = min(255, self.frequency[key] + 1)
            return
        if len(self.frequency) >= self.frequency_limit:
            weakest = min(self.frequency.values())
            for old_key in tuple(self.frequency):
                if self.frequency[old_key] == weakest:
                    del self.frequency[old_key]
                    if len(self.frequency) < self.frequency_limit:
                        break
        self.frequency[key] = 1

    def _remember(self, ghost, key):
        self.ghost_probation.pop(key, None)
        self.ghost_protected.pop(key, None)
        ghost[key] = None
        ghost.move_to_end(key)
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _rebalance(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size

    def _evict_one(self):
        if self.probation:
            key, size = self.probation.popitem(last=False)
            self._remember(self.ghost_probation, key)
        elif self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self._remember(self.ghost_protected, key)
        else:
            return None
        self.used_bytes -= size
        return key

    def _victim_plan(self, required):
        plan = []
        remaining = required
        for key, size in self.probation.items():
            if remaining <= 0:
                break
            plan.append((key, size))
            remaining -= size
        if remaining > 0:
            for key, size in self.protected.items():
                if remaining <= 0:
                    break
                plan.append((key, size))
                remaining -= size
        return plan

    def _admit(self, key, size, plan):
        candidate = self.frequency.get(key, 1)
        candidate_weight = max(1, isqrt(size))
        for old_key, old_size in plan:
            victim = self.frequency.get(old_key, 1)
            victim_weight = max(1, isqrt(old_size))
            if candidate * victim_weight < victim * candidate_weight:
                return False
        return True

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            self._record(key)
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            self._record(key)
            self._rebalance()
            return []

        self._record(key)
        if size <= 0 or size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        if key in self.ghost_probation:
            delta = max(1, max(self.capacity_bytes // 16, min(size, self.capacity_bytes)))
            self.protected_target = max(0, self.protected_target - delta)
        elif key in self.ghost_protected:
            delta = max(1, max(self.capacity_bytes // 16, min(size, self.capacity_bytes)))
            self.protected_target = min(self.capacity_bytes, self.protected_target + delta)
        self.ghost_probation.pop(key, None)
        self.ghost_protected.pop(key, None)

        required = max(0, self.used_bytes + size - self.capacity_bytes)
        plan = self._victim_plan(required)
        if not self._admit(key, size, plan):
            return []

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._evict_one()
            if old_key is None:
                break
            evicted.append(old_key)

        self.probation[key] = size
        self.used_bytes += size
        self._rebalance()
        return evicted
