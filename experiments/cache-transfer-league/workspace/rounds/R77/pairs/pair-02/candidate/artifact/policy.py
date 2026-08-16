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
        self._observed = 0
        self._hits = 0
        self._recent_cause = 0
        self._frequent_cause = 0
        self._state = 0
        self._intervention_done = False
        self._baseline_count = 0
        self._baseline_hits = 0
        self._active_count = 0
        self._active_hits = 0
        self._saved_target = self.recent_target
        self._intervention_shift = 0
        self._attributed_gain = 0

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

    def _maybe_begin_intervention(self):
        if self.capacity <= 0 or self._intervention_done or self._state != 0:
            return
        if self._observed < 16:
            return
        recent = self._recent_cause
        frequent = self._frequent_cause
        if recent < 2 or frequent < 2:
            return
        if abs(recent - frequent) * 2 > recent + frequent:
            return
        delta = max(1, self.capacity // 8)
        old_target = self.recent_target
        if recent >= frequent:
            new_target = min(self.capacity, old_target + delta)
            if new_target == old_target:
                new_target = max(0, old_target - delta)
        else:
            new_target = max(0, old_target - delta)
            if new_target == old_target:
                new_target = min(self.capacity, old_target + delta)
        if new_target == old_target:
            return
        self._saved_target = old_target
        self._intervention_shift = new_target - old_target
        self.recent_target = new_target
        self._baseline_count = self._observed
        self._baseline_hits = self._hits
        self._active_count = 0
        self._active_hits = 0
        self._state = 1
        self._intervention_done = True

    def _observe_intervention(self, hit):
        self._active_count += 1
        if hit:
            self._active_hits += 1
        if self._active_count < 24:
            return
        gain = (self._active_hits * self._baseline_count -
                self._baseline_hits * self._active_count)
        self._attributed_gain = gain
        if gain > 0 and 8 * gain >= self._active_count * self._baseline_count:
            self._state = 2
        else:
            self.recent_target = self._saved_target
            self._state = 0

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))
        was_active = self._state == 1
        self._observed += 1
        if self._observed % 32 == 0 and not was_active:
            self._recent_cause //= 2
            self._frequent_cause //= 2

        resident = key in self.recent or key in self.frequent
        if resident:
            self._hits += 1
            self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                evicted = [key]
            else:
                evicted = self._make_room(size, 0)
                self.frequent[key] = size
                self.frequent_bytes += size
                self.used += size
        else:
            ghost_kind = 1 if key in self.ghost_recent else 2 if key in self.ghost_frequent else 0
            if ghost_kind == 1:
                self._recent_cause += 1
            elif ghost_kind == 2:
                self._frequent_cause += 1
            if ghost_kind and self._state != 1:
                self._adjust_target(ghost_kind)
            if ghost_kind:
                self._drop_ghost(key)
            evicted = []
            if size > 0 and size <= self.capacity:
                evicted = self._make_room(size, ghost_kind)
                if ghost_kind:
                    self.frequent[key] = size
                    self.frequent_bytes += size
                else:
                    self.recent[key] = size
                    self.recent_bytes += size
                self.used += size

        if was_active:
            self._observe_intervention(resident)
        elif self._state == 0:
            self._maybe_begin_intervention()
        return evicted
