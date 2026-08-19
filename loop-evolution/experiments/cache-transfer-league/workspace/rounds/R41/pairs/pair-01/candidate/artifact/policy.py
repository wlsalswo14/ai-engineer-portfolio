from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        try:
            capacity = int(capacity_bytes)
        except (TypeError, ValueError, OverflowError):
            capacity = 0
        self.capacity_bytes = max(0, capacity)
        self._used = 0
        self._tick = 0
        self._items = {}
        self._probation = OrderedDict()
        self._protected = OrderedDict()
        self._ghost_probation = OrderedDict()
        self._ghost_protected = OrderedDict()
        self._ghost_limit = 512
        self._frequency = {}
        self._protected_target = (self.capacity_bytes * 55) // 100

    def _touch_frequency(self, key):
        value = self._frequency.get(key, 0)
        self._frequency[key] = min(value + 1, 1 << 20)

    def _decay(self):
        if self._tick % 256 != 0:
            return
        for key in list(self._frequency):
            value = self._frequency[key] >> 1
            if key in self._items or key in self._ghost_probation or key in self._ghost_protected:
                self._frequency[key] = max(1, value)
            elif value:
                self._frequency[key] = value
            else:
                del self._frequency[key]
        for item in self._items.values():
            item[2] = max(1, item[2] >> 1)

    def _remember_ghost(self, key, protected):
        self._ghost_probation.pop(key, None)
        self._ghost_protected.pop(key, None)
        ghosts = self._ghost_protected if protected else self._ghost_probation
        ghosts[key] = None
        while len(ghosts) > self._ghost_limit:
            ghosts.popitem(last=False)

    def _ghost_adjustment(self, key):
        step = max(1, self.capacity_bytes // 16)
        if key in self._ghost_probation:
            self._ghost_probation.pop(key, None)
            self._protected_target = max(0, self._protected_target - step)
        elif key in self._ghost_protected:
            self._ghost_protected.pop(key, None)
            self._protected_target = min(self.capacity_bytes, self._protected_target + step)

    def _victim_key(self, key):
        item = self._items[key]
        age = self._tick - item[3]
        return (
            self._frequency.get(key, 1),
            -age,
            -item[0],
            item[3],
        )

    def _utility(self, key, candidate=False):
        frequency = max(1, self._frequency.get(key, 1))
        if candidate:
            recent = 4
            protected_bonus = 0
        else:
            item = self._items[key]
            age = max(0, self._tick - item[3])
            recent = max(1, 4 - min(3, age // 32))
            protected_bonus = 2 if item[1] else 0
        return 4 * frequency + recent + protected_bonus

    def _make_room(self, size, candidate=None, force=False):
        if self._used + size <= self.capacity_bytes:
            return True
        needed = self._used + size - self.capacity_bytes
        victims = []
        probation = sorted(self._probation, key=self._victim_key)
        protected = sorted(self._protected, key=self._victim_key)
        ordered = probation + protected
        freed = 0
        candidate_utility = self._utility(candidate, True) if candidate is not None else 0
        for victim in ordered:
            victim_size = self._items[victim][0]
            if not force and candidate is not None:
                if candidate_utility * victim_size <= self._utility(victim) * size:
                    return False
            victims.append(victim)
            freed += victim_size
            if freed >= needed:
                break
        if freed < needed:
            return False
        for victim in victims:
            self._remove(victim, remember=True)
        return True

    def _remove(self, key, remember=False):
        item = self._items.pop(key, None)
        if item is None:
            return
        protected = item[1]
        if protected:
            self._protected.pop(key, None)
        else:
            self._probation.pop(key, None)
        self._used -= item[0]
        if remember:
            self._remember_ghost(key, protected)

    def _promote(self, key):
        item = self._items.get(key)
        if item is None or item[1]:
            return
        self._probation.pop(key, None)
        item[1] = True
        self._protected[key] = None
        while self._protected and self._protected_bytes() > self._protected_target:
            oldest = next(iter(self._protected))
            demoted = self._items[oldest]
            self._protected.pop(oldest, None)
            demoted[1] = False
            self._probation[oldest] = None

    def _protected_bytes(self):
        return sum(self._items[key][0] for key in self._protected)

    def _insert(self, key, size, force=False):
        if size <= 0 or size > self.capacity_bytes:
            return False
        if not self._make_room(size, key, force=force):
            return False
        self._items[key] = [size, False, 1, self._tick]
        self._probation[key] = None
        self._used += size
        return True

    def access(self, key, size, now):
        self._tick += 1
        self._decay()
        if type(key) is not int:
            return list(self._items)
        try:
            amount = int(size)
        except (TypeError, ValueError, OverflowError):
            return list(self._items)
        self._touch_frequency(key)
        self._ghost_adjustment(key)
        item = self._items.get(key)
        if amount <= 0:
            if item is not None:
                self._remove(key, remember=False)
            return list(self._items)
        if amount > self.capacity_bytes:
            if item is not None:
                self._remove(key, remember=False)
            return list(self._items)
        if item is not None:
            old_size = item[0]
            old_protected = item[1]
            old_hits = item[2]
            if amount != old_size:
                self._remove(key, remember=False)
                if self._insert(key, amount, force=True):
                    item = self._items[key]
                    item[2] = old_hits + 1
                    if old_protected or item[2] >= 2:
                        self._promote(key)
            else:
                item[2] = min(item[2] + 1, 1 << 20)
                item[3] = self._tick
                if not item[1] and item[2] >= 2:
                    self._promote(key)
            return list(self._items)
        self._insert(key, amount)
        return list(self._items)
