from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.entries = {}
        self.recent = OrderedDict()
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost = OrderedDict()
        self.used_bytes = 0
        self.recent_bytes = 0
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.sequence = 0
        self.window_fraction = 0.18
        self.protected_fraction = 0.58
        self.scan_pressure = 0.0
        self.period = 64
        self.period_requests = 0
        self.period_hits = 0
        self.period_misses = 0
        self.period_ghost_hits = 0
        self.ghost_limit = 2048

    def _remember_ghost(self, key):
        self.ghost[key] = self.sequence
        self.ghost.move_to_end(key)
        while len(self.ghost) > self.ghost_limit:
            self.ghost.popitem(last=False)

    def _remove_entry(self, key):
        entry = self.entries.pop(key, None)
        if entry is None:
            return 0
        size = entry[0]
        segment = entry[3]
        if segment == 0:
            self.recent.pop(key, None)
            self.recent_bytes -= size
        elif segment == 1:
            self.probation.pop(key, None)
            self.probation_bytes -= size
        else:
            self.protected.pop(key, None)
            self.protected_bytes -= size
        self.used_bytes -= size
        return size

    def _demote_oldest_protected(self):
        if not self.protected:
            return False
        key = next(iter(self.protected))
        entry = self.entries[key]
        size = entry[0]
        self.protected.pop(key)
        self.protected_bytes -= size
        self.probation[key] = None
        self.probation_bytes += size
        entry[3] = 1
        return True

    def _rebalance_recent(self):
        if self.capacity_bytes <= 0:
            return
        target = max(1, int(self.capacity_bytes * self.window_fraction))
        while self.recent and self.recent_bytes > target:
            key = next(iter(self.recent))
            entry = self.entries[key]
            size = entry[0]
            self.recent.pop(key)
            self.recent_bytes -= size
            self.probation[key] = None
            self.probation_bytes += size
            entry[3] = 1

    def _rebalance_protected(self):
        if self.capacity_bytes <= 0:
            return
        target = max(1, int(self.capacity_bytes * self.protected_fraction))
        while self.protected and self.protected_bytes > target:
            self._demote_oldest_protected()

    def _evict_oldest(self, queue):
        if not queue:
            return None
        key = next(iter(queue))
        self._remove_entry(key)
        self._remember_ghost(key)
        return key

    def _make_room(self, size):
        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            victim = None
            if self.probation:
                victim = self._evict_oldest(self.probation)
            elif self.recent:
                victim = self._evict_oldest(self.recent)
            elif self.protected:
                victim = self._evict_oldest(self.protected)
            if victim is None:
                break
            evicted.append(victim)
        return evicted

    def _promote(self, key):
        entry = self.entries[key]
        size = entry[0]
        segment = entry[3]
        if segment == 0:
            self.recent.pop(key, None)
            self.recent_bytes -= size
            self.protected[key] = None
            self.protected_bytes += size
            entry[3] = 2
        elif segment == 1:
            self.probation.pop(key, None)
            self.probation_bytes -= size
            self.protected[key] = None
            self.protected_bytes += size
            entry[3] = 2
        else:
            self.protected.move_to_end(key)

    def _age_protected(self):
        if not self.protected:
            return
        limit = self.period * (2 if self.scan_pressure >= 0.5 else 4)
        maximum = 8 if self.scan_pressure >= 0.5 else 2
        moved = 0
        while len(self.protected) > 1 and moved < maximum:
            key = next(iter(self.protected))
            if self.sequence - self.entries[key][1] <= limit:
                break
            if not self._demote_oldest_protected():
                break
            moved += 1

    def _finish_period(self, hit, ghost_hit):
        self.period_requests += 1
        if hit:
            self.period_hits += 1
        else:
            self.period_misses += 1
            if ghost_hit:
                self.period_ghost_hits += 1
        if self.period_requests < self.period:
            return
        reuse = self.period_hits / max(1, self.period_requests)
        novelty = self.period_misses / max(1, self.period_requests)
        ghost_rate = self.period_ghost_hits / max(1, self.period_misses)
        signal = min(1.0, novelty * (1.0 - reuse))
        self.scan_pressure = 0.65 * self.scan_pressure + 0.35 * signal
        if ghost_rate >= 0.12:
            self.window_fraction = 0.24
            self.protected_fraction = 0.54
        elif novelty >= 0.62 and reuse <= 0.28:
            self.window_fraction = 0.08
            self.protected_fraction = 0.72
        elif reuse >= 0.45:
            self.window_fraction = 0.20
            self.protected_fraction = 0.60
        else:
            self.window_fraction = 0.15
            self.protected_fraction = 0.63
        self._age_protected()
        self._rebalance_recent()
        self._rebalance_protected()
        self.period_requests = 0
        self.period_hits = 0
        self.period_misses = 0
        self.period_ghost_hits = 0

    def access(self, key: int, size: int, now: int) -> list[int]:
        self.sequence += 1
        request_size = max(0, int(size))
        entry = self.entries.get(key)
        if entry is not None:
            entry[1] = self.sequence
            entry[2] = min(entry[2] + 1, 1000000)
            self._promote(key)
            self._rebalance_protected()
            self._finish_period(True, False)
            return []

        ghost_hit = key in self.ghost
        if ghost_hit:
            self.ghost.pop(key, None)

        if self.capacity_bytes == 0 or request_size > self.capacity_bytes:
            self._finish_period(False, ghost_hit)
            return []

        if (not ghost_hit and self.used_bytes > self.capacity_bytes // 2
                and request_size * 3 > self.capacity_bytes):
            self._remember_ghost(key)
            self._finish_period(False, False)
            return []

        evicted = self._make_room(request_size)
        if self.used_bytes + request_size > self.capacity_bytes:
            self._finish_period(False, ghost_hit)
            return evicted

        segment = 2 if ghost_hit else 0
        self.entries[key] = [request_size, self.sequence, 1, segment]
        if segment == 2:
            self.protected[key] = None
            self.protected_bytes += request_size
        else:
            self.recent[key] = None
            self.recent_bytes += request_size
        self.used_bytes += request_size
        self._rebalance_recent()
        self._rebalance_protected()
        self._finish_period(False, ghost_hit)
        return evicted
