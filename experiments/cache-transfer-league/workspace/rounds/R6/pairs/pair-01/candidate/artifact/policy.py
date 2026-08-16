from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self._window = OrderedDict()
        self._probation = OrderedDict()
        self._protected = OrderedDict()
        self._window_bytes = 0
        self._probation_bytes = 0
        self._protected_bytes = 0
        self._used_bytes = 0
        self._frequency = OrderedDict()
        self._ghost = OrderedDict()
        self._calls = 0
        self._ghost_limit = 4096
        self._frequency_limit = 8192
        self._window_target = self.capacity_bytes // 8
        self._window_step = max(1, self.capacity_bytes // 32) if self.capacity_bytes else 0

    def _touch_frequency(self, key):
        value = self._frequency.pop(key, 0) + 1
        self._frequency[key] = min(255, value)
        while len(self._frequency) > self._frequency_limit:
            self._frequency.popitem(last=False)
        self._calls += 1
        if self._calls % 2048 == 0:
            for item in list(self._frequency):
                value = self._frequency[item] // 2
                if value:
                    self._frequency[item] = value
                else:
                    del self._frequency[item]

    def _adjust_window(self, ghost_hit):
        if not self.capacity_bytes:
            return
        if ghost_hit:
            self._window_target = min(
                self.capacity_bytes // 2,
                self._window_target + self._window_step,
            )
        elif self._calls % 64 == 0:
            self._window_target = max(0, self._window_target - self._window_step)

    def _protected_target(self):
        return max(0, (self.capacity_bytes - self._window_target) * 2 // 3)

    def _rebalance_window(self):
        while self._window and self._window_bytes > self._window_target:
            key, size = self._window.popitem(last=False)
            self._window_bytes -= size
            self._probation[key] = size
            self._probation_bytes += size

    def _rebalance_protected(self):
        target = self._protected_target()
        while self._protected and self._protected_bytes > target:
            key, size = self._protected.popitem(last=False)
            self._protected_bytes -= size
            self._probation[key] = size
            self._probation_bytes += size

    def _remove(self, key):
        if key in self._window:
            size = self._window.pop(key)
            self._window_bytes -= size
        elif key in self._probation:
            size = self._probation.pop(key)
            self._probation_bytes -= size
        elif key in self._protected:
            size = self._protected.pop(key)
            self._protected_bytes -= size
        else:
            return None
        self._used_bytes -= size
        return size

    def _remember_ghost(self, key):
        self._ghost.pop(key, None)
        self._ghost[key] = True
        while len(self._ghost) > self._ghost_limit:
            self._ghost.popitem(last=False)

    def _select_victim(self, keep_key):
        best_key = None
        best_score = None
        for rank, (key, size) in enumerate(self._probation.items()):
            if key != keep_key:
                frequency = self._frequency.get(key, 1)
                score = (frequency * 1048576) // max(1, size)
                if best_score is None or score < best_score:
                    best_key = key
                    best_score = score
            if rank >= 31:
                break
        if best_key is not None:
            return best_key
        for key in self._window:
            if key != keep_key:
                return key
        for key in self._protected:
            if key != keep_key:
                return key
        return None

    def _make_room(self, keep_key):
        evicted = []
        while self._used_bytes > self.capacity_bytes:
            victim = self._select_victim(keep_key)
            if victim is None:
                break
            self._remove(victim)
            self._remember_ghost(victim)
            evicted.append(victim)
        return evicted

    def _promote(self, key):
        size = self._probation.pop(key)
        self._probation_bytes -= size
        self._protected[key] = size
        self._protected_bytes += size
        self._rebalance_protected()

    def access(self, key: int, size: int, now: int) -> list[int]:
        request_size = max(0, int(size))
        self._touch_frequency(key)

        if key in self._window:
            stored_size = self._window.pop(key)
            self._window[key] = stored_size
            return []

        if key in self._probation:
            self._promote(key)
            return []

        if key in self._protected:
            stored_size = self._protected.pop(key)
            self._protected[key] = stored_size
            return []

        if self.capacity_bytes == 0 or request_size > self.capacity_bytes:
            return []

        ghost_hit = key in self._ghost
        if ghost_hit:
            del self._ghost[key]
        self._adjust_window(ghost_hit)

        self._window[key] = request_size
        self._window_bytes += request_size
        self._used_bytes += request_size
        self._rebalance_window()
        self._rebalance_protected()
        return self._make_room(key)
