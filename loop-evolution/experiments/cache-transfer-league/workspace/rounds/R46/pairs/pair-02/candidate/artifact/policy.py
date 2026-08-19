from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.t1_bytes = 0
        self.t2_bytes = 0
        self.probation_target = self.capacity_bytes // 2
        self.ghost_limit = max(64, min(8192, self.capacity_bytes // 4096 + 64))

    @property
    def used_bytes(self):
        return self.t1_bytes + self.t2_bytes

    def _remember(self, ghost, key):
        self.b1.pop(key, None)
        self.b2.pop(key, None)
        ghost.pop(key, None)
        ghost[key] = None
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _forget(self, key):
        self.b1.pop(key, None)
        self.b2.pop(key, None)

    def _adapt(self, key, size):
        delta = max(1, self.capacity_bytes // 32)
        delta = max(delta, min(size, self.capacity_bytes))
        if key in self.b1:
            self.b1.pop(key, None)
            self.probation_target = min(
                self.capacity_bytes,
                self.probation_target + delta,
            )
        elif key in self.b2:
            self.b2.pop(key, None)
            self.probation_target = max(
                0,
                self.probation_target - delta,
            )

    def _rebalance_segments(self):
        protected_target = self.capacity_bytes - self.probation_target
        while self.t2 and self.t2_bytes > protected_target:
            key, size = self.t2.popitem(last=False)
            self.t2_bytes -= size
            self.t1[key] = size
            self.t1_bytes += size

    def _evict_from(self, table, ghost, excluded):
        victim = None
        for candidate in table:
            if candidate != excluded:
                victim = candidate
                break
        if victim is None:
            return None
        size = table.pop(victim)
        if table is self.t1:
            self.t1_bytes -= size
        else:
            self.t2_bytes -= size
        self._remember(ghost, victim)
        return victim

    def _evict_one(self, excluded=None):
        prefer_t1 = bool(self.t1) and (
            self.t1_bytes > self.probation_target or not self.t2
        )
        if prefer_t1:
            victim = self._evict_from(self.t1, self.b1, excluded)
            if victim is not None:
                return victim
            return self._evict_from(self.t2, self.b2, excluded)
        victim = self._evict_from(self.t2, self.b2, excluded)
        if victim is not None:
            return victim
        return self._evict_from(self.t1, self.b1, excluded)

    def _remove_hit(self, table, key, new_size):
        old_size = table.pop(key)
        if table is self.t1:
            self.t1_bytes -= old_size
        else:
            self.t2_bytes -= old_size
        if new_size > self.capacity_bytes:
            return old_size, False
        if table is self.t1:
            self.t1[key] = new_size
            self.t1_bytes += new_size
        else:
            self.t2[key] = new_size
            self.t2_bytes += new_size
        return old_size, True

    def access(self, key: int, size: int, now: int) -> list[int]:
        del now
        size = int(size)

        if key in self.t2:
            old_size = self.t2[key]
            new_size = size if size > 0 else old_size
            self.t2.pop(key)
            self.t2_bytes -= old_size
            if new_size > self.capacity_bytes:
                return [key]
            self.t2[key] = new_size
            self.t2_bytes += new_size
            evicted = []
            while self.used_bytes > self.capacity_bytes:
                victim = self._evict_one(excluded=key)
                if victim is None:
                    self.t2.pop(key, None)
                    self.t2_bytes -= new_size
                    evicted.append(key)
                    break
                evicted.append(victim)
            return evicted

        if key in self.t1:
            old_size = self.t1.pop(key)
            self.t1_bytes -= old_size
            new_size = size if size > 0 else old_size
            if new_size > self.capacity_bytes:
                return [key]
            self.t2[key] = new_size
            self.t2_bytes += new_size
            self._rebalance_segments()
            evicted = []
            while self.used_bytes > self.capacity_bytes:
                victim = self._evict_one(excluded=key)
                if victim is None:
                    if key in self.t2:
                        self.t2.pop(key, None)
                        self.t2_bytes -= new_size
                    elif key in self.t1:
                        self.t1.pop(key, None)
                        self.t1_bytes -= new_size
                    evicted.append(key)
                    break
                evicted.append(victim)
            return evicted

        if size <= 0 or self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        self._adapt(key, size)
        self._forget(key)
        self._rebalance_segments()

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            victim = self._evict_one()
            if victim is None:
                return evicted
            evicted.append(victim)

        self.t1[key] = size
        self.t1_bytes += size
        return evicted
