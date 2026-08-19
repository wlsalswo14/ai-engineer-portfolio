from collections import OrderedDict
from math import isqrt


class Policy:
    def __init__(self, capacity_bytes):
        try:
            capacity_bytes = int(capacity_bytes)
        except (TypeError, ValueError):
            capacity_bytes = 0
        self.capacity_bytes = max(0, capacity_bytes)
        self._target = (self.capacity_bytes * 3) // 4
        self._cache = {}
        self._probation = OrderedDict()
        self._protected = OrderedDict()
        self._ghost_probation = OrderedDict()
        self._ghost_protected = OrderedDict()
        self._bytes = 0
        self._protected_bytes = 0
        self._tick = 0

    def _normal_size(self, size):
        try:
            size = int(size)
        except (TypeError, ValueError):
            size = 0
        return max(0, size)

    def _remember(self, key, protected):
        self._ghost_probation.pop(key, None)
        self._ghost_protected.pop(key, None)
        target = self._ghost_protected if protected else self._ghost_probation
        target[key] = self._tick
        limit = max(64, 4 * max(1, len(self._cache)) + 16)
        while len(self._ghost_probation) + len(self._ghost_protected) > limit:
            if self._ghost_probation and self._ghost_protected:
                left = next(iter(self._ghost_probation.items()))
                right = next(iter(self._ghost_protected.items()))
                source = self._ghost_probation if left[1] <= right[1] else self._ghost_protected
            elif self._ghost_probation:
                source = self._ghost_probation
            else:
                source = self._ghost_protected
            source.pop(next(iter(source)), None)

    def _adapt_from_ghost(self, key, size):
        if not self.capacity_bytes:
            self._ghost_probation.pop(key, None)
            self._ghost_protected.pop(key, None)
            return
        step = max(1, self.capacity_bytes // 16)
        if size > step:
            step = min(self.capacity_bytes, size)
        if key in self._ghost_probation:
            self._ghost_probation.pop(key, None)
            self._ghost_protected.pop(key, None)
            self._target = min(self.capacity_bytes, self._target + step)
        elif key in self._ghost_protected:
            self._ghost_protected.pop(key, None)
            self._ghost_probation.pop(key, None)
            self._target = max(0, self._target - step)

    def _remove_cached(self, key, remember=True):
        entry = self._cache.pop(key)
        if entry[3]:
            self._protected.pop(key, None)
            self._protected_bytes -= entry[0]
        else:
            self._probation.pop(key, None)
        self._bytes -= entry[0]
        if remember:
            self._remember(key, entry[3])
        return entry

    def _victim(self, pool):
        chosen = None
        chosen_score = None
        for key, entry in pool.items():
            age = self._tick - entry[2]
            divisor = max(1, age + 1) * isqrt(entry[0] + 1)
            score = ((entry[1] + 1) * 1000000) // divisor
            if chosen_score is None or score < chosen_score:
                chosen = key
                chosen_score = score
        return chosen

    def _demote_protected(self):
        while self._protected and self._protected_bytes > self._target:
            key = self._victim(self._protected)
            entry = self._protected.pop(key)
            entry[3] = False
            self._protected_bytes -= entry[0]
            self._probation[key] = entry

    def _evict_one(self, evicted):
        pool = self._probation if self._probation else self._protected
        if not pool:
            return False
        key = self._victim(pool)
        self._remove_cached(key, remember=True)
        evicted.append(key)
        return True

    def _ensure_room(self, required, evicted):
        while self._bytes + required > self.capacity_bytes:
            if not self._evict_one(evicted):
                break

    def _trim_ghosts(self):
        limit = max(64, 4 * max(1, len(self._cache)) + 16)
        while len(self._ghost_probation) + len(self._ghost_protected) > limit:
            if self._ghost_probation and self._ghost_protected:
                left = next(iter(self._ghost_probation.items()))
                right = next(iter(self._ghost_protected.items()))
                source = self._ghost_probation if left[1] <= right[1] else self._ghost_protected
            elif self._ghost_probation:
                source = self._ghost_probation
            else:
                source = self._ghost_protected
            source.pop(next(iter(source)), None)

    def access(self, key, size, now):
        size = self._normal_size(size)
        self._tick += 1
        evicted = []
        entry = self._cache.get(key)

        if entry is not None:
            if size > self.capacity_bytes:
                self._remove_cached(key, remember=False)
                evicted.append(key)
                while self._cache:
                    self._evict_one(evicted)
                return evicted

            self._bytes += size - entry[0]
            entry[0] = size
            entry[1] = min(entry[1] + 1, 1000000000)
            entry[2] = self._tick
            if entry[3]:
                self._protected.move_to_end(key)
            else:
                self._probation.pop(key, None)
                entry[3] = True
                self._protected[key] = entry
                self._protected_bytes += size
                self._demote_protected()
            self._ensure_room(0, evicted)
            self._trim_ghosts()
            return evicted

        self._adapt_from_ghost(key, size)
        if size > self.capacity_bytes:
            while self._cache:
                self._evict_one(evicted)
            self._trim_ghosts()
            return evicted

        entry = [size, 0, self._tick, False]
        self._cache[key] = entry
        self._probation[key] = entry
        self._bytes += size
        self._ensure_room(0, evicted)
        self._trim_ghosts()
        return evicted
