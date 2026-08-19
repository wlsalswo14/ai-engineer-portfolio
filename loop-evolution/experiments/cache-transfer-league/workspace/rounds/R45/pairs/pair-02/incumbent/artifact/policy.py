from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        try:
            capacity = int(capacity_bytes)
        except (TypeError, ValueError, OverflowError):
            capacity = 0
        self.capacity_bytes = max(0, capacity)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.ghost_limit = 4096
        self.protected_target = self.capacity_bytes // 2
        self.protected_bytes = 0
        self.used_bytes = 0
        self.frequency = {}
        self.frequency_order = OrderedDict()
        self.request_count = 0
        self.frequency_limit = 65536

    def _age_frequencies(self):
        for key in list(self.frequency):
            value = self.frequency[key] // 2
            if value:
                self.frequency[key] = value
            else:
                del self.frequency[key]
                self.frequency_order.pop(key, None)
        while len(self.frequency_order) > self.frequency_limit:
            key, _ = self.frequency_order.popitem(last=False)
            self.frequency.pop(key, None)

    def _touch_frequency(self, key):
        self.request_count += 1
        self.frequency[key] = min(255, self.frequency.get(key, 0) + 1)
        self.frequency_order.pop(key, None)
        self.frequency_order[key] = None
        if self.request_count % 4096 == 0 or len(self.frequency_order) > self.frequency_limit * 2:
            self._age_frequencies()

    def _remember(self, ghost, key):
        ghost.pop(key, None)
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

    def access(self, key: int, size: int, now: int) -> list[int]:
        if type(key) is not int:
            return []
        try:
            size = int(size)
        except (TypeError, ValueError, OverflowError):
            return []

        self._touch_frequency(key)

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

        if size <= 0 or self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        in_ghost_probation = key in self.ghost_probation
        in_ghost_protected = key in self.ghost_protected
        ghost_hit = in_ghost_probation or in_ghost_protected

        if in_ghost_probation:
            step = max(1, self.capacity_bytes // 16)
            self.protected_target = min(
                self.capacity_bytes,
                self.protected_target + max(step, min(size, self.capacity_bytes)),
            )
        elif in_ghost_protected:
            step = max(1, self.capacity_bytes // 16)
            self.protected_target = max(
                0,
                self.protected_target - max(step, min(size, self.capacity_bytes)),
            )

        self._forget_ghost(key)
        required = self.used_bytes + size - self.capacity_bytes
        candidate_frequency = self.frequency.get(key, 1)

        if required > 0:
            available = 0
            first_victim_frequency = None
            for victim_key, victim_size in list(self.probation.items()) + list(self.protected.items()):
                if first_victim_frequency is None:
                    first_victim_frequency = self.frequency.get(victim_key, 1)
                available += victim_size
                if available >= required:
                    break
            if available < required:
                return []
            if not ghost_hit and candidate_frequency <= first_victim_frequency:
                return []

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            victim = self._evict_one()
            if victim is None:
                return evicted
            evicted.append(victim)

        self.probation[key] = size
        self.used_bytes += size
        self._rebalance()
        return evicted
