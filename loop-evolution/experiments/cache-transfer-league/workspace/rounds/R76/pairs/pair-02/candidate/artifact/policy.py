from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.protected_bytes = 0
        self.used = 0
        self.recent_target = self.capacity // 2
        self._ghost_serial = 0
        self._ghost_bytes = 0
        self._ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self._ghost_count_limit = 4096
        self._ticks = 0
        self._frequency = {}
        self._period_total = 0
        self._period_hits = 0
        self._last_rate = None
        self._basis_generation = 0

    def _drop_ghost(self, key):
        value = self.ghost_recent.pop(key, None)
        if value is not None:
            self._ghost_bytes -= value[0]
        value = self.ghost_frequent.pop(key, None)
        if value is not None:
            self._ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, kind):
        self._drop_ghost(key)
        self._ghost_serial += 1
        value = (max(1, int(size)), self._ghost_serial)
        if kind == 1:
            self.ghost_recent[key] = value
        else:
            self.ghost_frequent[key] = value
        self._ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self._ghost_bytes > self._ghost_limit or
               len(self.ghost_recent) + len(self.ghost_frequent) > self._ghost_count_limit):
            recent_serial = None
            frequent_serial = None
            if self.ghost_recent:
                recent_serial = next(iter(self.ghost_recent.values()))[1]
            if self.ghost_frequent:
                frequent_serial = next(iter(self.ghost_frequent.values()))[1]
            if frequent_serial is None or (recent_serial is not None and recent_serial < frequent_serial):
                _, value = self.ghost_recent.popitem(last=False)
            else:
                _, value = self.ghost_frequent.popitem(last=False)
            self._ghost_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        recent_ghost_bytes = sum(value[0] for value in self.ghost_recent.values())
        frequent_ghost_bytes = sum(value[0] for value in self.ghost_frequent.values())
        if kind == 1:
            delta = (self.capacity if recent_ghost_bytes == 0 else
                     max(1, min(self.capacity, frequent_ghost_bytes // recent_ghost_bytes or 1)))
            self.recent_target = min(self.capacity, self.recent_target + delta)
        else:
            delta = (self.capacity if frequent_ghost_bytes == 0 else
                     max(1, min(self.capacity, recent_ghost_bytes // frequent_ghost_bytes or 1)))
            self.recent_target = max(0, self.recent_target - delta)
        self._trim_protected()

    def _protected_limit(self):
        return max(0, (self.capacity - self.recent_target) * 3 // 4)

    def _trim_protected(self):
        while self.protected and self.protected_bytes > self._protected_limit():
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.frequent[key] = size
            self.frequent_bytes += size

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
        value = self.protected.pop(key, None)
        if value is not None:
            self.protected_bytes -= value
            self.used -= value
            return value, 3
        return 0, 0

    def _pop_probation(self):
        candidates = []
        for index, (key, size) in enumerate(self.frequent.items()):
            candidates.append((self._frequency.get(key, 1), index, key, size))
            if index >= 7:
                break
        if not candidates:
            return None
        _, _, key, size = min(candidates, key=lambda item: (item[0], item[1]))
        del self.frequent[key]
        self.frequent_bytes -= size
        self.used -= size
        return key, size

    def _evict_one(self, prefer_recent):
        if prefer_recent and self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 1)
            return key
        probation = self._pop_probation()
        if probation is not None:
            key, size = probation
            self._remember_ghost(key, size, 2)
            return key
        if self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.frequent[key] = size
            self.frequent_bytes += size
            probation = self._pop_probation()
            if probation is not None:
                key, size = probation
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
            if ghost_kind == 1 and self.recent:
                prefer_recent = True
            elif ghost_kind == 2 and self.frequent:
                prefer_recent = False
            key = self._evict_one(prefer_recent)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def _record(self, key):
        self._ticks += 1
        self._frequency[key] = min(255, self._frequency.get(key, 0) + 1)
        if self._ticks % 2048 == 0:
            for item_key in list(self._frequency):
                value = self._frequency[item_key] // 2
                if value:
                    self._frequency[item_key] = value
                else:
                    del self._frequency[item_key]
        if len(self._frequency) > 8192:
            ordered = sorted(self._frequency.items(), key=lambda item: (item[1], item[0]))
            for item_key, _ in ordered[:len(ordered) // 4]:
                self._frequency.pop(item_key, None)

    def _reset_causal_basis(self):
        self.ghost_recent.clear()
        self.ghost_frequent.clear()
        self._ghost_bytes = 0
        self._frequency.clear()
        while self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.frequent[key] = size
            self.frequent_bytes += size
        self.recent_target = self.capacity // 2
        self._basis_generation += 1

    def _finish(self, evicted, hit):
        self._period_total += 1
        if hit:
            self._period_hits += 1
        if self._period_total >= 128:
            rate = self._period_hits / self._period_total
            if (self._last_rate is not None and
                    self._last_rate >= 0.35 and
                    rate < max(0.08, self._last_rate * 0.55)):
                self._reset_causal_basis()
            self._last_rate = rate
            self._period_total = 0
            self._period_hits = 0
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))
        self._record(key)

        old_size, resident_kind = self._remove_resident(key)
        if resident_kind:
            if size <= 0 or size > self.capacity:
                return self._finish([key], True)
            evicted = self._make_room(size, 0)
            self._drop_ghost(key)
            if resident_kind == 1:
                self.frequent[key] = size
                self.frequent_bytes += size
            elif resident_kind == 2:
                self.protected[key] = size
                self.protected_bytes += size
            else:
                self.protected[key] = size
            self.used += size
            self._trim_protected()
            return self._finish(evicted, True)

        ghost_kind = 1 if key in self.ghost_recent else 2 if key in self.ghost_frequent else 0
        if size <= 0 or size > self.capacity:
            return self._finish([], False)

        if ghost_kind:
            self._adjust_target(ghost_kind)
            self._drop_ghost(key)

        evicted = self._make_room(size, ghost_kind)
        if self.used + size > self.capacity:
            return self._finish(evicted, False)
        if ghost_kind:
            self.frequent[key] = size
            self.frequent_bytes += size
        else:
            self.recent[key] = size
            self.recent_bytes += size
        self.used += size
        return self._finish(evicted, False)
