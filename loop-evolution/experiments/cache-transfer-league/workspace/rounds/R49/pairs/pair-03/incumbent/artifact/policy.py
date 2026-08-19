from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.ghost_limit = 4096
        self.protected_target = self.capacity_bytes // 2
        self.protected_bytes = 0
        self.used_bytes = 0
        self.frequencies = {}
        self.request_count = 0

    def _touch_frequency(self, key):
        self.request_count += 1
        if self.request_count % 512 == 0:
            for known in tuple(self.frequencies):
                value = self.frequencies[known] // 2
                if value <= 0:
                    del self.frequencies[known]
                else:
                    self.frequencies[known] = value
        self.frequencies[key] = min(1048576, self.frequencies.get(key, 0) + 1)

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

    def _victim(self, segment):
        selected_key = None
        selected_size = 0
        selected_frequency = 0
        for key, size in segment.items():
            frequency = max(1, self.frequencies.get(key, 1))
            if selected_key is None or frequency * selected_size < selected_frequency * size:
                selected_key = key
                selected_size = size
                selected_frequency = frequency
        return selected_key, selected_size

    def _evict_one(self):
        if self.probation:
            segment = self.probation
            ghost = self.ghost_probation
        elif self.protected:
            segment = self.protected
            ghost = self.ghost_protected
        else:
            return None

        key, size = self._victim(segment)
        segment.pop(key)
        if segment is self.protected:
            self.protected_bytes -= size
        self.used_bytes -= size
        self._remember(ghost, key)
        return key

    def access(self, key: int, size: int, now: int) -> list[int]:
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

        step = max(1, self.capacity_bytes // 16)
        if key in self.ghost_probation:
            self.protected_target = min(
                self.capacity_bytes,
                self.protected_target + max(step, min(size, self.capacity_bytes)),
            )
        elif key in self.ghost_protected:
            self.protected_target = max(
                0,
                self.protected_target - max(step, min(size, self.capacity_bytes)),
            )
        self._forget_ghost(key)

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._evict_one()
            if old_key is None:
                return evicted
            evicted.append(old_key)

        self.probation[key] = size
        self.used_bytes += size
        self._rebalance()
        return evicted
