from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.history = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0
        self.tick = 0
        self.max_history = 4096

    def _cached(self, key):
        return key in self.probation or key in self.protected

    def _trim_history(self):
        if len(self.history) <= self.max_history:
            return
        for old_key in list(self.history.keys()):
            if len(self.history) <= self.max_history:
                break
            if not self._cached(old_key):
                del self.history[old_key]

    def _age_history(self):
        for key, value in list(self.history.items()):
            aged = (value + 1) // 2
            if aged == 0 and not self._cached(key):
                del self.history[key]
            else:
                self.history[key] = aged

    def _bump(self, key):
        value = min(255, self.history.get(key, 0) + 1)
        if key in self.history:
            del self.history[key]
        self.history[key] = value
        self._trim_history()

    def _value(self, key, size):
        frequency = self.history.get(key, 1)
        return (frequency * 100000) // (max(0, size) + 64)

    def _rebalance_protected(self):
        target = (self.capacity_bytes * 2) // 3
        while self.protected and self.protected_bytes > target:
            old_key, old_size = self.protected.popitem(last=False)
            self.protected_bytes -= old_size
            self.probation[old_key] = old_size

    def _select_victims(self, size, candidate_value):
        selected = []
        selected_keys = set()
        simulated_used = self.used_bytes

        while simulated_used + size > self.capacity_bytes:
            pool = []
            for key, stored_size in self.probation.items():
                if key not in selected_keys:
                    pool.append((key, stored_size))
            if not pool:
                for key, stored_size in self.protected.items():
                    if key not in selected_keys:
                        pool.append((key, stored_size))
            if not pool:
                return None

            victim_key, victim_size = pool[0]
            victim_value = self._value(victim_key, victim_size)
            for key, stored_size in pool[1:]:
                value = self._value(key, stored_size)
                if value < victim_value:
                    victim_key = key
                    victim_size = stored_size
                    victim_value = value

            if candidate_value <= victim_value:
                return None
            selected.append((victim_key, victim_size))
            selected_keys.add(victim_key)
            simulated_used -= victim_size

        return selected

    def access(self, key: int, size: int, now: int) -> list[int]:
        self.tick += 1
        if self.tick % 256 == 0:
            self._age_history()
        self._bump(key)

        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            self._rebalance_protected()
            return []

        if size < 0 or size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        candidate_value = self._value(key, size)
        victims = self._select_victims(size, candidate_value)
        if victims is None:
            return []

        evicted = []
        for victim_key, victim_size in victims:
            if victim_key in self.probation:
                self.probation.pop(victim_key)
            elif victim_key in self.protected:
                self.protected.pop(victim_key)
                self.protected_bytes -= victim_size
            else:
                continue
            self.used_bytes -= victim_size
            evicted.append(victim_key)

        self.probation[key] = size
        self.used_bytes += size
        self._rebalance_protected()
        return evicted
