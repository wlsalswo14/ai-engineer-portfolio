from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.used = 0
        self.resident = {}
        self.window = OrderedDict()
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_window = OrderedDict()
        self.ghost_main = OrderedDict()
        self.frequency = {}
        self.events = 0
        self.stamp = 0
        self.last_now = None
        self.ghost_limit = 128
        self.window_target = max(1, self.capacity // 5) if self.capacity else 0

    def _remember(self, ghost, key):
        ghost[key] = None
        ghost.move_to_end(key)
        while len(ghost) > self.ghost_limit:
            old, _ = ghost.popitem(last=False)
            if old not in self.resident and old not in self.ghost_window and old not in self.ghost_main:
                self.frequency.pop(old, None)

    def _record(self, key):
        self.frequency[key] = min(255, self.frequency.get(key, 0) + 1)
        self.events += 1
        if self.events >= 4096:
            self.events = 0
            for item in list(self.frequency):
                value = self.frequency[item] // 2
                if value:
                    self.frequency[item] = value
                elif item in self.resident or item in self.ghost_window or item in self.ghost_main:
                    self.frequency[item] = 1
                else:
                    self.frequency.pop(item, None)

    def _drop(self, key, evicted):
        record = self.resident.pop(key, None)
        if record is None:
            return
        size, segment = record
        self.used -= size
        self.window.pop(key, None)
        self.probation.pop(key, None)
        self.protected.pop(key, None)
        if segment == "window":
            self._remember(self.ghost_window, key)
        else:
            self._remember(self.ghost_main, key)
        if key not in evicted:
            evicted.append(key)

    def _victim(self, exclude=None):
        for queue in (self.probation, self.window, self.protected):
            for key in queue:
                if key != exclude:
                    return key
        return None

    def _make_room(self, extra, exclude, evicted):
        while self.used + extra > self.capacity:
            victim = self._victim(exclude)
            if victim is None:
                return False
            self._drop(victim, evicted)
        return True

    def _touch(self, key):
        record = self.resident[key]
        segment = record[1]
        if segment == "window":
            self.window.move_to_end(key)
        elif segment == "probation":
            self.probation.pop(key, None)
            self.protected[key] = None
            record[1] = "protected"
        else:
            self.protected.move_to_end(key)

    def _rebalance_protected(self):
        target = max(1, self.capacity // 2) if self.capacity else 0
        total = sum(self.resident[key][0] for key in self.protected)
        while self.protected and total > target:
            key, _ = self.protected.popitem(last=False)
            record = self.resident.get(key)
            if record is not None:
                record[1] = "probation"
                self.probation[key] = None
                total -= record[0]

    def _rebalance_window(self, evicted):
        while self.window and sum(self.resident[key][0] for key in self.window) > self.window_target:
            candidate, _ = self.window.popitem(last=False)
            victim = next(iter(self.probation), None)
            if victim is not None and self.frequency.get(candidate, 0) < self.frequency.get(victim, 0):
                self._drop(candidate, evicted)
            else:
                if victim is not None:
                    self._drop(victim, evicted)
                record = self.resident.get(candidate)
                if record is not None:
                    record[1] = "probation"
                    self.probation[candidate] = None

    def access(self, key: int, size: int, now: int) -> list[int]:
        size = max(0, int(size))
        self.last_now = now
        self.stamp += 1
        evicted = []
        self._record(key)

        if key in self.resident:
            record = self.resident[key]
            if size > self.capacity:
                for item in list(self.resident):
                    self._drop(item, evicted)
                return evicted
            delta = size - record[0]
            if delta > 0 and not self._make_room(delta, key, evicted):
                self._drop(key, evicted)
                return evicted
            record[0] = size
            self.used += delta
            self._touch(key)
            self._rebalance_protected()
            self._rebalance_window(evicted)
            return evicted

        if self.capacity == 0 or size > self.capacity:
            for item in list(self.resident):
                self._drop(item, evicted)
            return evicted

        in_main_ghost = key in self.ghost_main
        in_window_ghost = key in self.ghost_window
        self.ghost_main.pop(key, None)
        self.ghost_window.pop(key, None)
        if in_window_ghost:
            self.window_target = min(self.capacity, self.window_target + max(1, self.capacity // 20))
        elif in_main_ghost:
            self.window_target = max(1, self.window_target - max(1, self.capacity // 20))

        self._make_room(size, None, evicted)
        segment = "probation" if in_main_ghost else "window"
        self.resident[key] = [size, segment]
        self.used += size
        if segment == "window":
            self.window[key] = None
        else:
            self.probation[key] = None
        self._rebalance_window(evicted)
        self._rebalance_protected()
        return evicted
