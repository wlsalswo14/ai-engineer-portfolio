from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.used = 0
        self.recent_used = 0
        self.frequent_used = 0
        self.recent_target = self.capacity // 2
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.recent_ghost = OrderedDict()
        self.frequent_ghost = OrderedDict()
        self.ghost_limit = 8192
        self.resident_limit = 65536

    def _forget_ghost(self, key):
        self.recent_ghost.pop(key, None)
        self.frequent_ghost.pop(key, None)

    def _remember_ghost(self, ghost, key):
        self._forget_ghost(key)
        ghost[key] = None
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _remove(self, key, queue, evicted=None, remember=True):
        if queue is self.recent:
            size = queue.pop(key)
            self.recent_used -= size
            provenance = self.recent_ghost
        else:
            size = queue.pop(key)
            self.frequent_used -= size
            provenance = self.frequent_ghost
        self.used -= size
        if remember:
            self._remember_ghost(provenance, key)
        if evicted is not None and key not in evicted:
            evicted.append(key)

    def _evict_one(self, evicted):
        if self.recent and (not self.frequent or self.recent_used > self.recent_target):
            key = next(iter(self.recent))
            self._remove(key, self.recent, evicted)
        elif self.frequent:
            key = next(iter(self.frequent))
            self._remove(key, self.frequent, evicted)
        elif self.recent:
            key = next(iter(self.recent))
            self._remove(key, self.recent, evicted)

    def _adjust_target(self, key, size):
        step = max(1, self.capacity // 64, size)
        if key in self.recent_ghost:
            self.recent_target = min(self.capacity, self.recent_target + step)
        elif key in self.frequent_ghost:
            self.recent_target = max(0, self.recent_target - step)

    def access(self, key: int, size: int, now: int) -> list[int]:
        del now
        size = max(0, int(size))
        evicted = []

        if key in self.recent:
            old = self.recent[key]
            if size > self.capacity:
                self._remove(key, self.recent, evicted)
                return evicted
            self.recent.pop(key)
            self.recent_used -= old
            self.used -= old
            self.frequent[key] = size
            self.frequent_used += size
            self.used += size
            self._forget_ghost(key)
        elif key in self.frequent:
            old = self.frequent[key]
            if size > self.capacity:
                self._remove(key, self.frequent, evicted)
                return evicted
            self.frequent.pop(key)
            self.frequent_used -= old
            self.used -= old
            self.frequent[key] = size
            self.frequent_used += size
            self.used += size
            self._forget_ghost(key)
        else:
            if self.capacity == 0 or size > self.capacity:
                return evicted
            self._adjust_target(key, size)
            self._forget_ghost(key)
            while self.used + size > self.capacity:
                self._evict_one(evicted)
            self.recent[key] = size
            self.recent_used += size
            self.used += size

        while len(self.recent) + len(self.frequent) > self.resident_limit:
            self._evict_one(evicted)
        while self.used > self.capacity and (self.recent or self.frequent):
            self._evict_one(evicted)
        return evicted
