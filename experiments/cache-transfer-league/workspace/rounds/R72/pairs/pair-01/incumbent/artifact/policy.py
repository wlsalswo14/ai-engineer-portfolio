from collections import OrderedDict

class Policy:
    def __init__(self, capacity_bytes: int):
        try:
            capacity = int(capacity_bytes)
        except (TypeError, ValueError):
            capacity = 0
        self._capacity = max(0, capacity)
        self._target = 0
        self._recent = OrderedDict()
        self._frequent = OrderedDict()
        self._ghost_recent = OrderedDict()
        self._ghost_frequent = OrderedDict()
        self._recent_bytes = 0
        self._frequent_bytes = 0
        self._ghost_recent_bytes = 0
        self._ghost_frequent_bytes = 0
        self._ghost_limit = 4096

    def _size(self, size):
        try:
            value = int(size)
        except (TypeError, ValueError):
            value = 0
        return max(0, value)

    def _forget_ghost(self, key):
        if key in self._ghost_recent:
            self._ghost_recent_bytes -= self._ghost_recent.pop(key)
            return
        if key in self._ghost_frequent:
            self._ghost_frequent_bytes -= self._ghost_frequent.pop(key)

    def _remember_ghost(self, key, size, frequent):
        self._forget_ghost(key)
        value = max(0, int(size))
        if frequent:
            self._ghost_frequent[key] = value
            self._ghost_frequent_bytes += value
        else:
            self._ghost_recent[key] = value
            self._ghost_recent_bytes += value
        while len(self._ghost_recent) + len(self._ghost_frequent) > self._ghost_limit:
            if self._ghost_recent:
                old_key, old_size = self._ghost_recent.popitem(last=False)
                self._ghost_recent_bytes -= old_size
            else:
                old_key, old_size = self._ghost_frequent.popitem(last=False)
                self._ghost_frequent_bytes -= old_size

    def _oldest_other(self, entries, protected):
        for key in entries:
            if key != protected:
                return key
        return None

    def _evict_one(self, protected):
        recent_key = self._oldest_other(self._recent, protected)
        frequent_key = self._oldest_other(self._frequent, protected)
        if self._recent_bytes > self._target and recent_key is not None:
            size = self._recent.pop(recent_key)
            self._recent_bytes -= size
            self._remember_ghost(recent_key, size, False)
            return recent_key
        if frequent_key is not None:
            size = self._frequent.pop(frequent_key)
            self._frequent_bytes -= size
            self._remember_ghost(frequent_key, size, True)
            return frequent_key
        if recent_key is not None:
            size = self._recent.pop(recent_key)
            self._recent_bytes -= size
            self._remember_ghost(recent_key, size, False)
            return recent_key
        return None

    def _fit(self, protected, evicted):
        while self._recent_bytes + self._frequent_bytes > self._capacity:
            victim = self._evict_one(protected)
            if victim is None:
                break
            evicted.append(victim)

    def access(self, key: int, size: int, now: int) -> list[int]:
        del now
        requested = self._size(size)
        evicted = []

        if key in self._recent:
            old_size = self._recent.pop(key)
            self._recent_bytes -= old_size
            if requested > self._capacity:
                self._remember_ghost(key, old_size, False)
                return [key]
            self._frequent[key] = requested
            self._frequent_bytes += requested
            self._fit(key, evicted)
            return evicted

        if key in self._frequent:
            old_size = self._frequent.pop(key)
            self._frequent_bytes -= old_size
            if requested > self._capacity:
                self._remember_ghost(key, old_size, True)
                return [key]
            self._frequent[key] = requested
            self._frequent_bytes += requested
            self._fit(key, evicted)
            return evicted

        in_recent_ghost = key in self._ghost_recent
        in_frequent_ghost = key in self._ghost_frequent
        if in_recent_ghost:
            denominator = max(1, self._ghost_recent_bytes)
            delta = max(1, self._ghost_frequent_bytes // denominator)
            self._target = min(self._capacity, self._target + delta)
            self._forget_ghost(key)
            if requested > self._capacity:
                return []
            self._frequent[key] = requested
            self._frequent_bytes += requested
            self._fit(key, evicted)
            return evicted

        if in_frequent_ghost:
            denominator = max(1, self._ghost_frequent_bytes)
            delta = max(1, self._ghost_recent_bytes // denominator)
            self._target = max(0, self._target - delta)
            self._forget_ghost(key)
            if requested > self._capacity:
                return []
            self._frequent[key] = requested
            self._frequent_bytes += requested
            self._fit(key, evicted)
            return evicted

        if requested > self._capacity:
            return []
        self._recent[key] = requested
        self._recent_bytes += requested
        self._fit(key, evicted)
        return evicted
