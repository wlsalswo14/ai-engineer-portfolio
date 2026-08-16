from collections import OrderedDict, deque


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.ghost_recent_bytes = 0
        self.ghost_frequent_bytes = 0
        self.used = 0
        self.recent_target = self.capacity // 2
        self._ghost_serial = 0
        self._ghost_bytes = 0
        self._ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self._ghost_count_limit = 4096
        self._evidence = deque(maxlen=64)
        self._outcomes = deque(maxlen=32)
        self._requests = 0
        self._mode = 0
        self._intervention_left = 0
        self._attribution_left = 0
        self._probe = {}
        self._probe_admitted = 0
        self._probe_hits = 0
        self._probe_misses = 0
        self._pre_rate = 0.0
        self._target_before = self.recent_target
        self._probe_target = self.recent_target
        self._last_intervention = -1000000

    def _drop_ghost(self, key):
        value = self.ghost_recent.pop(key, None)
        if value is not None:
            self.ghost_recent_bytes -= value[0]
            self._ghost_bytes -= value[0]
        value = self.ghost_frequent.pop(key, None)
        if value is not None:
            self.ghost_frequent_bytes -= value[0]
            self._ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, kind):
        self._drop_ghost(key)
        self._ghost_serial += 1
        value = (max(1, int(size)), self._ghost_serial)
        if kind == 1:
            self.ghost_recent[key] = value
            self.ghost_recent_bytes += value[0]
        else:
            self.ghost_frequent[key] = value
            self.ghost_frequent_bytes += value[0]
        self._ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self._ghost_bytes > self._ghost_limit or
               len(self.ghost_recent) + len(self.ghost_frequent) > self._ghost_count_limit):
            kind = 0
            serial = None
            if self.ghost_recent:
                kind = 1
                serial = next(iter(self.ghost_recent.values()))[1]
            if self.ghost_frequent:
                other = next(iter(self.ghost_frequent.values()))[1]
                if serial is None or other < serial:
                    kind = 2
            ghosts = self.ghost_recent if kind == 1 else self.ghost_frequent
            _, value = ghosts.popitem(last=False)
            if kind == 1:
                self.ghost_recent_bytes -= value[0]
            else:
                self.ghost_frequent_bytes -= value[0]
            self._ghost_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0 or self._mode or self._attribution_left:
            return
        b1 = self.ghost_recent_bytes
        b2 = self.ghost_frequent_bytes
        if kind == 1:
            delta = self.capacity if b1 == 0 else max(1, min(self.capacity, b2 // b1 or 1))
            self.recent_target = min(self.capacity, self.recent_target + delta)
        else:
            delta = self.capacity if b2 == 0 else max(1, min(self.capacity, b1 // b2 or 1))
            self.recent_target = max(0, self.recent_target - delta)

    def _remove_resident(self, key):
        value = self.recent.pop(key, None)
        if value is not None:
            self.recent_bytes -= value
            self.used -= value
            return value, 1
        value = self.frequent.pop(key, None)
        if value is not None:
            self.frequent_bytes -= value
            self.used -= value
            return value, 2
        return 0, 0

    def _retire_probe(self, key, hit):
        if key not in self._probe:
            return
        del self._probe[key]
        if hit:
            self._probe_hits += 1
        else:
            self._probe_misses += 1

    def _evict_one(self, prefer_recent):
        if prefer_recent and self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self.used -= size
            self._retire_probe(key, False)
            self._remember_ghost(key, size, 1)
            return key
        if self.frequent:
            key, size = self.frequent.popitem(last=False)
            self.frequent_bytes -= size
            self.used -= size
            self._retire_probe(key, False)
            self._remember_ghost(key, size, 2)
            return key
        if self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self.used -= size
            self._retire_probe(key, False)
            self._remember_ghost(key, size, 1)
            return key
        return None

    def _make_room(self, incoming, ghost_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            prefer_recent = self.recent_bytes > self.recent_target
            if ghost_kind == 1 and self.recent_bytes >= self.recent_target:
                prefer_recent = True
            key = self._evict_one(prefer_recent)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def _record_request(self, hit):
        self._requests += 1
        self._outcomes.append(1 if hit else 0)

    def _finalize_intervention(self):
        observed = self._probe_hits + self._probe_misses
        retain = False
        if observed >= 3:
            rate = self._probe_hits / float(observed)
            retain = self._probe_hits > self._probe_misses and rate >= self._pre_rate
        if retain:
            self.recent_target = self._probe_target
        else:
            self.recent_target = self._target_before
        self._probe.clear()
        self._attribution_left = 0
        self._evidence.clear()
        self._last_intervention = self._requests

    def _finish_intervention(self):
        self._mode = 0
        self._intervention_left = 0
        self._attribution_left = 64
        if self._probe_hits + self._probe_misses >= 3:
            self._finalize_intervention()

    def _advance_control(self):
        if self._mode:
            self._intervention_left -= 1
            if self._intervention_left <= 0:
                self._finish_intervention()
        elif self._attribution_left:
            self._attribution_left -= 1
            if self._attribution_left <= 0:
                self._finalize_intervention()
        else:
            self._maybe_start_intervention()

    def _maybe_start_intervention(self):
        if self.capacity <= 0 or self._requests < 16:
            return
        if self._requests - self._last_intervention < 64:
            return
        recent_events = sum(1 for kind in self._evidence if kind == 1)
        frequent_events = sum(1 for kind in self._evidence if kind == 2)
        if recent_events < 2 or frequent_events < 2:
            return
        self._pre_rate = sum(self._outcomes) / float(len(self._outcomes) or 1)
        self._target_before = self.recent_target
        high = min(self.capacity, max(0, (3 * self.capacity + 1) // 4))
        low = min(self.capacity, self.capacity // 4)
        self._probe_target = high if self.recent_target < self.capacity // 2 else low
        self.recent_target = self._probe_target
        self._mode = 1
        self._intervention_left = 24
        self._probe.clear()
        self._probe_admitted = 0
        self._probe_hits = 0
        self._probe_misses = 0
        self._evidence.clear()

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))
        hit = key in self.recent or key in self.frequent

        if hit:
            self._retire_probe(key, True)
            self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                evicted = [key]
            else:
                evicted = self._make_room(size, 0)
                self._drop_ghost(key)
                self.frequent[key] = size
                self.frequent_bytes += size
                self.used += size
        elif size <= 0 or size > self.capacity:
            evicted = []
        else:
            ghost_kind = 1 if key in self.ghost_recent else 2 if key in self.ghost_frequent else 0
            if ghost_kind:
                self._evidence.append(ghost_kind)
                self._adjust_target(ghost_kind)
                self._drop_ghost(key)
            evicted = self._make_room(size, ghost_kind)
            if ghost_kind:
                self.frequent[key] = size
                self.frequent_bytes += size
            else:
                self.recent[key] = size
                self.recent_bytes += size
            self.used += size
            if self._mode:
                self._probe[key] = True
                self._probe_admitted += 1

        self._record_request(hit)
        self._advance_control()
        return evicted
