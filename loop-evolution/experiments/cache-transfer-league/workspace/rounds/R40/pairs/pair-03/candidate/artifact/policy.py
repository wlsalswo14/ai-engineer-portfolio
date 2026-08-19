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
        self.frequency = {}
        self.last_touch = {}
        self.clock = 0
        self.misses = 0
        self.ghost_hits = 0
        self.b1_hits = 0
        self.b2_hits = 0
        self.alternations = 0
        self.last_ghost = None
        self.reconstituted = False

    def _remember(self, ghost, key):
        self.ghost_probation.pop(key, None)
        self.ghost_protected.pop(key, None)
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
        self.frequency.pop(key, None)
        self.last_touch.pop(key, None)
        return key

    def _reconstitute(self):
        entries = list(self.probation.items()) + list(self.protected.items())
        entries.sort(
            key=lambda item: (
                self.frequency.get(item[0], 1),
                self.last_touch.get(item[0], 0),
            ),
            reverse=True,
        )
        self.probation.clear()
        self.protected.clear()
        self.protected_bytes = 0
        for key, size in entries:
            if self.protected_bytes + size <= self.protected_target:
                self.protected[key] = size
                self.protected_bytes += size
            else:
                self.probation[key] = size
        self.ghost_probation.clear()
        self.ghost_protected.clear()
        self.ghost_hits = 0
        self.b1_hits = 0
        self.b2_hits = 0
        self.alternations = 0
        self.last_ghost = None
        self.reconstituted = True

    def _observe_nonrepresentability(self, side):
        if side is None or self.reconstituted:
            return
        self.ghost_hits += 1
        if side == "b1":
            self.b1_hits += 1
        else:
            self.b2_hits += 1
        if self.last_ghost is not None and self.last_ghost != side:
            self.alternations += 1
        self.last_ghost = side
        if (
            self.b1_hits >= 2
            and self.b2_hits >= 2
            and self.alternations >= 3
        ) or (self.misses >= 64 and self.ghost_hits >= 8):
            self._reconstitute()

    def access(self, key: int, size: int, now: int) -> list[int]:
        self.clock += 1
        self.last_touch[key] = self.clock

        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            self.frequency[key] = self.frequency.get(key, 1) + 1
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            self.frequency[key] = self.frequency.get(key, 1) + 1
            self._rebalance()
            return []

        if size <= 0 or self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        self.misses += 1
        side = None
        if key in self.ghost_probation:
            side = "b1"
        elif key in self.ghost_protected:
            side = "b2"
        self._observe_nonrepresentability(side)

        step = max(1, self.capacity_bytes // 16)
        delta = max(step, min(size, self.capacity_bytes))
        if side == "b1":
            self.protected_target = min(self.capacity_bytes, self.protected_target + delta)
        elif side == "b2":
            self.protected_target = max(0, self.protected_target - delta)
        self._forget_ghost(key)

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._evict_one()
            if old_key is None:
                break
            evicted.append(old_key)

        self.probation[key] = size
        self.frequency[key] = 1
        self.last_touch[key] = self.clock
        self.used_bytes += size
        self._rebalance()
        return evicted
