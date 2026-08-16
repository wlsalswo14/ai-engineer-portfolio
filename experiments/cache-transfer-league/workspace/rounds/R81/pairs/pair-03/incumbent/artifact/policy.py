from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.items = OrderedDict()
        self.used = 0
        self.tick = 0
        self.decay_period = 128
        self.history_limit = 8192
        self.history = OrderedDict()
        self.sample_width = 128

    def _effective_frequency(self, frequency, stamp):
        age = self.tick - stamp
        if age <= 0:
            return max(1, int(frequency))
        shifts = min(8, age // self.decay_period)
        return max(1, int(frequency) >> shifts)

    def _record_access(self, key):
        value = self.history.pop(key, None)
        if value is None:
            frequency = 1
        else:
            frequency = min(255, self._effective_frequency(value[0], value[1]) + 1)
        self.history[key] = (frequency, self.tick)
        while len(self.history) > self.history_limit:
            self.history.popitem(last=False)
        return frequency

    def _eviction_plan(self, required):
        if required <= 0:
            return []
        keys = list(self.items)
        selected = set()
        plan = []
        remaining = required
        while remaining > 0:
            visible = min(len(keys), self.sample_width + 8 * len(plan))
            best_key = None
            best_rank = None
            for candidate in keys[:visible]:
                if candidate in selected:
                    continue
                value = self.items.get(candidate)
                if value is None:
                    continue
                rank = (self._effective_frequency(value[1], value[2]), value[2])
                if best_rank is None or rank < best_rank:
                    best_key = candidate
                    best_rank = rank
            if best_key is None:
                break
            selected.add(best_key)
            plan.append(best_key)
            remaining -= self.items[best_key][0]
        return plan

    def _evict(self, keys):
        evicted = []
        for key in keys:
            value = self.items.pop(key, None)
            if value is not None:
                self.used -= value[0]
                evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))
        self.tick += 1
        observed_frequency = self._record_access(key)

        current = self.items.pop(key, None)
        if current is not None:
            self.used -= current[0]
            frequency = min(
                255,
                max(
                    observed_frequency,
                    self._effective_frequency(current[1], current[2]) + 1,
                ),
            )
            if size <= 0 or size > self.capacity:
                return [key]
            required = self.used + size - self.capacity
            evicted = self._evict(self._eviction_plan(required))
            self.items[key] = [size, frequency, self.tick]
            self.used += size
            return evicted

        if size <= 0 or size > self.capacity:
            return []

        required = self.used + size - self.capacity
        evicted = self._evict(self._eviction_plan(required))
        self.items[key] = [size, observed_frequency, self.tick]
        self.used += size
        return evicted
