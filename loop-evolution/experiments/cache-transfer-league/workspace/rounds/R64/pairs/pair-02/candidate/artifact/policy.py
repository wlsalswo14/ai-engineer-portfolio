from collections import OrderedDict

class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.p = self.capacity // 2
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.t1_bytes = 0
        self.t2_bytes = 0
        self._ghost_each = 2048

    def _clean_size(self, size):
        value = int(size)
        return value if value >= 0 else 0

    def _drop(self, group, key):
        value = group.pop(key)
        if group is self.t1:
            self.t1_bytes -= value
        else:
            self.t2_bytes -= value
        return value

    def _remember_ghost(self, key, size, from_t1):
        self.b1.pop(key, None)
        self.b2.pop(key, None)
        target = self.b1 if from_t1 else self.b2
        target[key] = max(0, int(size))
        while len(target) > self._ghost_each:
            target.popitem(last=False)

    def _evict_one(self, prefer_t1, exclude=None):
        groups = (self.t1, self.t2) if prefer_t1 else (self.t2, self.t1)
        for group in groups:
            for candidate in group:
                if exclude is not None and candidate == exclude:
                    continue
                value = self._drop(group, candidate)
                return candidate, value, group is self.t1
        return None, None, None

    def _make_room(self, amount, prefer_t1, exclude=None):
        evicted = []
        while self.t1_bytes + self.t2_bytes + amount > self.capacity:
            key, value, from_t1 = self._evict_one(prefer_t1, exclude)
            if key is None:
                break
            self._remember_ghost(key, value, from_t1)
            evicted.append(key)
        return evicted

    def _trim_t1(self, amount):
        evicted = []
        while self.t1 and self.t1_bytes + amount > self.p:
            key, value, from_t1 = self._evict_one(True)
            if key is None:
                break
            self._remember_ghost(key, value, from_t1)
            evicted.append(key)
        return evicted

    def _trim_t2(self, amount):
        target = self.capacity - self.p
        evicted = []
        while self.t2 and self.t2_bytes + amount > target:
            key, value, from_t1 = self._evict_one(False)
            if key is None:
                break
            self._remember_ghost(key, value, from_t1)
            evicted.append(key)
        return evicted

    def _admit(self, key, amount, frequent):
        if amount > self.capacity:
            return []
        evicted = self._trim_t2(amount) if frequent else self._trim_t1(amount)
        prefer_t1 = self.t1_bytes >= self.p
        evicted.extend(self._make_room(amount, prefer_t1))
        if self.t1_bytes + self.t2_bytes + amount > self.capacity:
            return evicted
        group = self.t2 if frequent else self.t1
        group[key] = amount
        if frequent:
            self.t2_bytes += amount
        else:
            self.t1_bytes += amount
        return evicted

    def _adapt(self, from_b1, old_size, new_size):
        limit = self.capacity if self.capacity > 0 else 1
        step = max(1, min(limit, max(int(old_size), int(new_size))))
        if from_b1:
            self.p = min(self.capacity, self.p + step)
        else:
            self.p = max(0, self.p - step)

    def access(self, key: int, size: int, now: int) -> list[int]:
        amount = self._clean_size(size)

        if key in self.t1:
            old_size = self._drop(self.t1, key)
            if amount > self.capacity:
                self._remember_ghost(key, old_size, True)
                return [key]
            self.t2[key] = amount
            self.t2_bytes += amount
            return self._make_room(0, self.t1_bytes >= self.p, key)

        if key in self.t2:
            old_size = self._drop(self.t2, key)
            if amount > self.capacity:
                self._remember_ghost(key, old_size, False)
                return [key]
            self.t2[key] = amount
            self.t2_bytes += amount
            return self._make_room(0, self.t1_bytes >= self.p, key)

        if key in self.b1:
            old_size = self.b1.pop(key)
            self._adapt(True, old_size, amount)
            if amount > self.capacity:
                return []
            return self._admit(key, amount, True)

        if key in self.b2:
            old_size = self.b2.pop(key)
            self._adapt(False, old_size, amount)
            if amount > self.capacity:
                return []
            return self._admit(key, amount, True)

        if amount > self.capacity:
            return []
        return self._admit(key, amount, False)
