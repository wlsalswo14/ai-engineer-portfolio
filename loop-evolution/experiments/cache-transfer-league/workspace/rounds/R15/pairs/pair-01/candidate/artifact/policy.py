from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.recent = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.recent_bytes = 0
        self.protected_bytes = 0
        self.used_bytes = 0
        self.protected_target = self.capacity_bytes // 2
        self.max_ghost = 4096
        self.freq = {}
        self.freq_order = OrderedDict()
        self.max_frequency_entries = 8192
        self.clock = 0

    def _touch_frequency(self, key):
        value = min(255, self.freq.get(key, 0) + 1)
        self.freq[key] = value
        self.freq_order.pop(key, None)
        self.freq_order[key] = None
        while len(self.freq_order) > self.max_frequency_entries:
            old_key, _ = self.freq_order.popitem(last=False)
            self.freq.pop(old_key, None)
        return value

    def _age_frequencies(self):
        for key in list(self.freq):
            value = self.freq[key]
            if value > 1:
                self.freq[key] = max(1, value // 2)

    def _remember_ghost(self, key, protected):
        self.ghost_recent.pop(key, None)
        self.ghost_protected.pop(key, None)
        target = self.ghost_protected if protected else self.ghost_recent
        target[key] = None
        while len(self.ghost_recent) + len(self.ghost_protected) > self.max_ghost:
            if len(self.ghost_recent) >= len(self.ghost_protected):
                self.ghost_recent.popitem(last=False)
            else:
                self.ghost_protected.popitem(last=False)

    def _adjust_target(self, key):
        step = max(1, self.capacity_bytes // 16) if self.capacity_bytes else 0
        if key in self.ghost_protected:
            self.ghost_protected.pop(key, None)
            self.protected_target = min(self.capacity_bytes, self.protected_target + step)
        elif key in self.ghost_recent:
            self.ghost_recent.pop(key, None)
            self.protected_target = max(0, self.protected_target - step)
            self._rebalance_protected()
        self.ghost_recent.pop(key, None)
        self.ghost_protected.pop(key, None)

    def _rebalance_protected(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.protected[key] = size
            self.recent_bytes += size
            self.recent[key] = size

    def _evict_one(self):
        recent_limit = self.capacity_bytes - self.protected_target
        if self.recent and (self.recent_bytes > recent_limit or not self.protected):
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            protected = False
        elif self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            protected = True
        elif self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            protected = False
        else:
            return None
        self.used_bytes -= size
        self._remember_ghost(key, protected)
        return key

    def _enforce_capacity(self):
        evicted = []
        while self.used_bytes > self.capacity_bytes:
            key = self._evict_one()
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        size = max(0, size)
        self.clock += 1
        if self.clock % 1024 == 0:
            self._age_frequencies()

        if key in self.recent:
            stored = self.recent.pop(key)
            self.recent_bytes -= stored
            self.used_bytes -= stored
            self._touch_frequency(key)
            if size > self.capacity_bytes:
                self._remember_ghost(key, False)
                return [key]
            self.protected[key] = size
            self.protected_bytes += size
            self.used_bytes += size
            self._rebalance_protected()
            return self._enforce_capacity()

        if key in self.protected:
            stored = self.protected.pop(key)
            self.protected_bytes -= stored
            self.used_bytes -= stored
            self._touch_frequency(key)
            if size > self.capacity_bytes:
                self._remember_ghost(key, True)
                return [key]
            self.protected[key] = size
            self.protected_bytes += size
            self.used_bytes += size
            return self._enforce_capacity()

        self._adjust_target(key)
        self._touch_frequency(key)
        if size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        self.recent[key] = size
        self.recent_bytes += size
        self.used_bytes += size
        return self._enforce_capacity()
