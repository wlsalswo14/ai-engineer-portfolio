from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.bytes_used = 0
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.target_recent = self.capacity * 0.5
        self.clock = 0
        self.resident = {}
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()

    def _forget_ghost(self, key):
        self.ghost_recent.pop(key, None)
        self.ghost_frequent.pop(key, None)

    def _trim_ghosts(self):
        limit = max(32, 2 * max(1, len(self.resident)))
        while len(self.ghost_recent) + len(self.ghost_frequent) > limit:
            if len(self.ghost_recent) >= len(self.ghost_frequent):
                self.ghost_recent.popitem(last=False)
            else:
                self.ghost_frequent.popitem(last=False)

    def _add_ghost(self, key, segment, size):
        self._forget_ghost(key)
        target = self.ghost_recent if segment == 'R' else self.ghost_frequent
        target[key] = max(0, int(size))
        self._trim_ghosts()

    def _adjust_target(self, direction, size):
        if self.capacity <= 0:
            self.target_recent = 0.0
            return
        delta = max(1.0, min(float(self.capacity), float(max(1, size))))
        self.target_recent += direction * delta
        self.target_recent = max(0.0, min(float(self.capacity), self.target_recent))

    def _detach(self, key):
        entry = self.resident.pop(key)
        if entry['segment'] == 'R':
            self.recent.pop(key, None)
            self.recent_bytes -= entry['size']
        else:
            self.frequent.pop(key, None)
            self.frequent_bytes -= entry['size']
        self.bytes_used -= entry['size']
        return entry

    def _insert(self, key, size, segment, frequency, now):
        entry = {
            'size': size,
            'segment': segment,
            'frequency': frequency,
            'last': now,
            'stamp': self.clock,
        }
        self.resident[key] = entry
        if segment == 'R':
            self.recent[key] = None
            self.recent_bytes += size
        else:
            self.frequent[key] = None
            self.frequent_bytes += size
        self.bytes_used += size

    def _victim(self):
        if self.recent and (self.recent_bytes > self.target_recent or not self.frequent):
            return next(iter(self.recent))
        if self.frequent:
            return next(iter(self.frequent))
        if self.recent:
            return next(iter(self.recent))
        return None

    def _make_room(self, incoming_size, evicted):
        while self.bytes_used + incoming_size > self.capacity:
            victim = self._victim()
            if victim is None:
                break
            entry = self._detach(victim)
            self._add_ghost(victim, entry['segment'], entry['size'])
            if victim not in evicted:
                evicted.append(victim)

    def access(self, key: int, size: int, now: int) -> list[int]:
        size = max(0, int(size))
        self.clock += 1
        evicted = []

        if key in self.resident:
            old = self._detach(key)
            old_segment = old['segment']
            if size > self.capacity:
                self._add_ghost(key, old_segment, old['size'])
                return [key]
            segment = 'F' if old_segment == 'F' or old_segment == 'R' else 'R'
            frequency = max(2, old['frequency'] + 1)
            self._forget_ghost(key)
            self._make_room(size, evicted)
            if self.bytes_used + size <= self.capacity:
                self._insert(key, size, segment, frequency, now)
            else:
                self._add_ghost(key, segment, size)
                if key not in evicted:
                    evicted.append(key)
            return evicted

        in_recent_ghost = key in self.ghost_recent
        in_frequent_ghost = key in self.ghost_frequent
        if in_recent_ghost:
            self._adjust_target(1, self.ghost_recent[key])
            segment = 'F'
            frequency = 2
        elif in_frequent_ghost:
            self._adjust_target(-1, self.ghost_frequent[key])
            segment = 'F'
            frequency = 2
        else:
            segment = 'R'
            frequency = 1
        self._forget_ghost(key)

        if size > self.capacity:
            self._add_ghost(key, segment, size)
            return []

        self._make_room(size, evicted)
        if self.bytes_used + size <= self.capacity:
            self._insert(key, size, segment, frequency, now)
        else:
            self._add_ghost(key, segment, size)
        return evicted
