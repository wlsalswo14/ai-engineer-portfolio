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
        self.protected_target = (self.capacity_bytes * 3) // 5
        self.protected_bytes = 0
        self.used_bytes = 0
        self.frequency = {}
        self.operations = 0

    def _record(self, key):
        self.operations += 1
        if self.operations % 2048 == 0:
            for old_key in tuple(self.frequency):
                value = self.frequency[old_key] >> 1
                if value:
                    self.frequency[old_key] = value
                else:
                    del self.frequency[old_key]
        value = self.frequency.get(key, 0)
        if value < 1000000000:
            value += 1
        self.frequency[key] = value
        return value

    def _remember(self, ghost, key):
        self.ghost_probation.pop(key, None)
        self.ghost_protected.pop(key, None)
        ghost[key] = None
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _forget_ghost(self, key):
        self.ghost_probation.pop(key, None)
        self.ghost_protected.pop(key, None)

    def _rebalance(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size

    def _victim(self):
        if self.probation:
            return next(iter(self.probation))
        if self.protected:
            return next(iter(self.protected))
        return None

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

    def _priority(self, key, size):
        count = max(1, self.frequency.get(key, 0))
        size_factor = 32 + min(128, isqrt(max(1, int(size))))
        return count * size_factor

    def access(self, key: int, size: int, now: int) -> list[int]:
        self._record(key)

        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            self._rebalance()
            return []

        item_size = int(size)
        if item_size <= 0 or item_size > self.capacity_bytes:
            return []

        step = max(1, self.capacity_bytes // 32)
        if key in self.ghost_probation:
            self.protected_target = min(
                self.capacity_bytes,
                self.protected_target + max(step, min(item_size, self.capacity_bytes)),
            )
        elif key in self.ghost_protected:
            self.protected_target = max(
                0,
                self.protected_target - max(step, min(item_size, self.capacity_bytes)),
            )
        self._rebalance()

        victim = self._victim()
        if victim is not None and self.used_bytes + item_size > self.capacity_bytes:
            if self._priority(key, item_size) < self._priority(
                victim,
                self.probation.get(victim, self.protected.get(victim, 1)),
            ):
                self._remember(self.ghost_probation, key)
                return []

        self._forget_ghost(key)
        evicted = []
        while self.used_bytes + item_size > self.capacity_bytes:
            old_key = self._evict_one()
            if old_key is None:
                break
            evicted.append(old_key)

        self.probation[key] = item_size
        self.used_bytes += item_size
        self._rebalance()
        return evicted
