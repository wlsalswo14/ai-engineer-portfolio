from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        self.capacity = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.used = 0
        self.protected_target = self.capacity // 2

        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.ghost_probation_bytes = 0
        self.ghost_protected_bytes = 0
        self.ghost_bytes = 0
        self.ghost_limit = max(64, min(1 << 20, 4 * max(1, self.capacity)))
        self.ghost_count_limit = 4096
        self.serial = 0

        self.width_mask = 2047
        self.mask64 = (1 << 64) - 1
        self.seeds = (0x9E3779B97F4A7C15, 0xD1B54A32D192ED03, 0x94D049BB133111EB, 0xBF58476D1CE4E5B9)
        self.sketch = [[0] * 2048 for _ in range(4)]
        self.samples = 0

    def _index(self, key, seed):
        x = ((int(key) & self.mask64) + seed) & self.mask64
        x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & self.mask64
        x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & self.mask64
        return (x ^ (x >> 31)) & self.width_mask

    def _estimate(self, key):
        result = 255
        for row, seed in zip(self.sketch, self.seeds):
            value = row[self._index(key, seed)]
            if value < result:
                result = value
        return result

    def _touch_frequency(self, key):
        for row, seed in zip(self.sketch, self.seeds):
            index = self._index(key, seed)
            if row[index] < 255:
                row[index] += 1
        self.samples += 1
        if self.samples >= 4096:
            for row in self.sketch:
                for index, value in enumerate(row):
                    row[index] = value >> 1
            self.samples = 0

    def _drop_ghost(self, key):
        value = self.ghost_probation.pop(key, None)
        if value is not None:
            self.ghost_probation_bytes -= value[0]
            self.ghost_bytes -= value[0]
        value = self.ghost_protected.pop(key, None)
        if value is not None:
            self.ghost_protected_bytes -= value[0]
            self.ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, protected):
        self._drop_ghost(key)
        self.serial += 1
        value = (max(1, int(size)), self.serial)
        if protected:
            self.ghost_protected[key] = value
            self.ghost_protected_bytes += value[0]
        else:
            self.ghost_probation[key] = value
            self.ghost_probation_bytes += value[0]
        self.ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_probation) + len(self.ghost_protected) > self.ghost_count_limit):
            probation_key = next(iter(self.ghost_probation), None)
            protected_key = next(iter(self.ghost_protected), None)
            if protected_key is None or (
                probation_key is not None and
                self.ghost_probation[probation_key][1] < self.ghost_protected[protected_key][1]
            ):
                value = self.ghost_probation.pop(probation_key)
                self.ghost_probation_bytes -= value[0]
            else:
                value = self.ghost_protected.pop(protected_key)
                self.ghost_protected_bytes -= value[0]
            self.ghost_bytes -= value[0]

    def _adapt(self, kind):
        if self.capacity <= 0:
            return
        if kind == 1:
            if self.ghost_probation_bytes:
                delta = self.ghost_protected_bytes // self.ghost_probation_bytes
                delta = max(1, min(self.capacity, delta))
            else:
                delta = self.capacity
            self.protected_target = min(self.capacity, self.protected_target + delta)
        else:
            if self.ghost_protected_bytes:
                delta = self.ghost_probation_bytes // self.ghost_protected_bytes
                delta = max(1, min(self.capacity, delta))
            else:
                delta = self.capacity
            self.protected_target = max(0, self.protected_target - delta)

    def _remove_resident(self, key):
        value = self.probation.pop(key, None)
        if value is not None:
            self.probation_bytes -= value
            self.used -= value
            return value, 0
        value = self.protected.pop(key, None)
        if value is not None:
            self.protected_bytes -= value
            self.used -= value
            return value, 1
        return None, None

    def _victim_plan(self, incoming):
        need = self.used + incoming - self.capacity
        plan = []
        for store, protected in ((self.probation, 0), (self.protected, 1)):
            for key, size in store.items():
                plan.append((key, size, protected))
                need -= size
                if need <= 0:
                    return plan
        return plan

    def _evict(self, key, protected):
        if protected:
            size = self.protected.pop(key)
            self.protected_bytes -= size
        else:
            size = self.probation.pop(key)
            self.probation_bytes -= size
        self.used -= size
        self._remember_ghost(key, size, protected)
        return key

    def _make_room(self, incoming, candidate_frequency=None):
        plan = self._victim_plan(incoming)
        if candidate_frequency is not None:
            for key, _, _ in plan:
                if candidate_frequency <= self._estimate(key):
                    return []
        evicted = []
        for key, _, protected in plan:
            evicted.append(self._evict(key, protected))
        return evicted

    def _rebalance(self):
        while self.protected_bytes > self.protected_target and self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size
            self.probation_bytes += size

    def access(self, key, size, now):
        key = int(key)
        size = max(0, int(size))
        self._touch_frequency(key)

        if key in self.probation:
            old_size = self.probation.pop(key)
            self.probation_bytes -= old_size
            self.used -= old_size
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size)
            if self.used + size > self.capacity:
                return evicted + [key]
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            self._rebalance()
            return evicted

        if key in self.protected:
            old_size = self.protected.pop(key)
            self.protected_bytes -= old_size
            self.used -= old_size
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size)
            if self.used + size > self.capacity:
                return evicted + [key]
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            self._rebalance()
            return evicted

        if size <= 0 or size > self.capacity:
            return []

        ghost_kind = 1 if key in self.ghost_probation else 2 if key in self.ghost_protected else 0
        if ghost_kind:
            self._adapt(ghost_kind)

        evicted = self._make_room(size, self._estimate(key))
        if self.used + size > self.capacity:
            return evicted

        if ghost_kind:
            self._drop_ghost(key)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            self._rebalance()
        else:
            self.probation[key] = size
            self.probation_bytes += size
            self.used += size
        return evicted
