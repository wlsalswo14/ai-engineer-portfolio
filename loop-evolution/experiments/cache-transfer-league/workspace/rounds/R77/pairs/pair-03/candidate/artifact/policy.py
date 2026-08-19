from collections import OrderedDict


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
        self._recent_evidence = 0
        self._frequent_evidence = 0
        self._last_ghost_kind = 0
        self._ambiguity_streak = 0
        self._probe_pending = None
        self._probe_age = 0
        self._probe_cooldown = 0
        self._causal_bias = 0

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
        if self.capacity <= 0:
            return
        if kind == 1:
            b1 = self.ghost_recent_bytes
            b2 = self.ghost_frequent_bytes
            delta = self.capacity if b1 == 0 else max(1, min(self.capacity, b2 // b1 or 1))
            self.recent_target = min(self.capacity, self.recent_target + delta)
        else:
            b1 = self.ghost_recent_bytes
            b2 = self.ghost_frequent_bytes
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

    def _evict_one(self, prefer_recent):
        if prefer_recent and self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 1)
            return key
        if self.frequent:
            key, size = self.frequent.popitem(last=False)
            self.frequent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 2)
            return key
        if self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 1)
            return key
        return None

    def _make_room(self, incoming, ghost_kind, forced_kind=0):
        evicted = []
        while self.used + incoming > self.capacity:
            if forced_kind == 1 and self.recent:
                prefer_recent = True
            elif forced_kind == 2 and self.frequent:
                prefer_recent = False
            else:
                prefer_recent = self.recent_bytes > self.recent_target
                if ghost_kind == 1 and self.recent_bytes >= self.recent_target:
                    prefer_recent = True
            key = self._evict_one(prefer_recent)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def _observe_ambiguity(self, kind):
        previous = self._last_ghost_kind
        if kind == 1:
            self._recent_evidence = min(8, self._recent_evidence + 1)
        elif kind == 2:
            self._frequent_evidence = min(8, self._frequent_evidence + 1)
        else:
            self._recent_evidence = max(0, self._recent_evidence - 1)
            self._frequent_evidence = max(0, self._frequent_evidence - 1)
        if (kind and previous and kind != previous and
                self._recent_evidence >= 2 and self._frequent_evidence >= 2):
            self._ambiguity_streak = min(8, self._ambiguity_streak + 1)
        else:
            self._ambiguity_streak = max(0, self._ambiguity_streak - 1)
        if kind:
            self._last_ghost_kind = kind

    def _record_probe(self, success):
        pending = self._probe_pending
        if pending is None:
            return
        lane = pending[1]
        signal = 1 if success else -1
        if lane == 1:
            self._causal_bias = max(-4, min(4, self._causal_bias + signal))
        else:
            self._causal_bias = max(-4, min(4, self._causal_bias - signal))
        self._ambiguity_streak = max(0, self._ambiguity_streak - 3)
        self._probe_pending = None
        self._probe_age = 0
        self._probe_cooldown = max(self._probe_cooldown, 4)

    def _observe_probe_request(self, key):
        if self._probe_pending is None:
            return
        self._probe_age += 1
        pending_key = self._probe_pending[0]
        if key == pending_key:
            if key in self.recent or key in self.frequent:
                self._record_probe(True)
            elif key in self.ghost_recent or key in self.ghost_frequent:
                self._record_probe(False)
        if self._probe_pending is not None and self._probe_age >= 8:
            self._probe_pending = None
            self._probe_age = 0

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))
        if self._probe_cooldown > 0:
            self._probe_cooldown -= 1
        self._observe_probe_request(key)

        if key in self.recent or key in self.frequent:
            self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            self._drop_ghost(key)
            self.frequent[key] = size
            self.frequent_bytes += size
            self.used += size
            if self._probe_pending is not None and key in evicted:
                self._record_probe(False)
            return evicted

        ghost_kind = 1 if key in self.ghost_recent else 2 if key in self.ghost_frequent else 0
        self._observe_ambiguity(ghost_kind)
        if size <= 0 or size > self.capacity:
            return []

        if ghost_kind:
            self._adjust_target(ghost_kind)
            self._drop_ghost(key)

        probe_lane = 0
        if (self.capacity > 0 and self._probe_pending is None and
                self._probe_cooldown == 0 and self._ambiguity_streak >= 3):
            probe_lane = 1 if self._causal_bias >= 0 else 2
            self._probe_pending = (key, probe_lane)
            self._probe_age = 0
            self._probe_cooldown = 16

        evicted = self._make_room(size, ghost_kind, probe_lane)
        if probe_lane == 2 or (probe_lane == 0 and ghost_kind):
            self.frequent[key] = size
            self.frequent_bytes += size
        else:
            self.recent[key] = size
            self.recent_bytes += size
        self.used += size

        if self._probe_pending is not None and self._probe_pending[0] in evicted:
            self._record_probe(False)
        return evicted
