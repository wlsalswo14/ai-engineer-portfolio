from collections import OrderedDict


class _Entry:
    __slots__ = ('key', 'size', 'last', 'segment', 'hits')

    def __init__(self, key, size, last):
        self.key = key
        self.size = size
        self.last = last
        self.segment = 0
        self.hits = 1


class Policy:
    def __init__(self, capacity_bytes):
        try:
            capacity = int(capacity_bytes)
        except (TypeError, ValueError):
            capacity = 0
        self.capacity_bytes = max(0, capacity)
        self._entries = {}
        self._probationary = OrderedDict()
        self._protected = OrderedDict()
        self._frequency = {}
        self._ghost = OrderedDict()
        self._bytes = 0
        self._protected_bytes = 0
        self._protected_target = (self.capacity_bytes * 3) // 5
        if self.capacity_bytes > 0 and self._protected_target == 0:
            self._protected_target = 1
        self._ghost_bytes = 0
        self._ghost_byte_limit = max(4096, min(max(1, self.capacity_bytes) * 2, 16777216))
        self._ghost_entry_limit = 8192
        self._tick = 0
        self._touches = 0

    def access(self, key, size, now):
        try:
            requested = int(size)
        except (TypeError, ValueError):
            requested = 1
        requested = max(1, requested)
        self._tick += 1
        self._touches += 1
        self._touch_frequency(key)
        _ = now

        ghost = self._discard_ghost(key)
        if ghost is not None:
            ghost_segment, ghost_size = ghost
            step = max(1, min(max(1, self.capacity_bytes // 8), max(1, ghost_size)))
            if ghost_segment == 0:
                self._protected_target = min(self.capacity_bytes, self._protected_target + step)
            else:
                self._protected_target = max(0, self._protected_target - step)

        entry = self._entries.get(key)
        if entry is not None:
            if requested > self.capacity_bytes:
                return [self._remove_key(key)]
            self._bytes += requested - entry.size
            entry.size = requested
            entry.last = self._tick
            entry.hits = min(3, entry.hits + 1)
            if entry.segment == 0:
                self._probationary.move_to_end(key)
                if entry.hits >= 2:
                    self._promote(entry)
            else:
                self._protected.move_to_end(key)
            return self._make_room(0, key)

        if requested > self.capacity_bytes:
            evicted = []
            for cached_key in list(self._entries):
                evicted.append(self._remove_key(cached_key))
            return evicted

        evicted = self._make_room(requested, None)
        entry = _Entry(key, requested, self._tick)
        if ghost is not None and ghost[0] == 1:
            entry.hits = 2
        self._entries[key] = entry
        self._probationary[key] = entry
        self._bytes += requested
        if entry.hits >= 2:
            self._promote(entry)
        return evicted

    def _touch_frequency(self, key):
        self._frequency[key] = min((1 << 30), self._frequency.get(key, 0) + 1)
        if self._touches % 4096 == 0:
            for cached_key, value in list(self._frequency.items()):
                value //= 2
                if value:
                    self._frequency[cached_key] = value
                else:
                    del self._frequency[cached_key]

    def _retention_score(self, entry):
        frequency = self._frequency.get(entry.key, 1)
        age = max(0, self._tick - entry.last)
        recency = 1025 // (age + 1)
        return (frequency + entry.hits) * recency * 1024 // max(1, entry.size)

    def _victim_key(self, exclude):
        victim = None
        victim_score = None
        for key in self._probationary:
            if exclude is not None and key == exclude:
                continue
            score = self._retention_score(self._entries[key])
            if victim is None or score < victim_score:
                victim = key
                victim_score = score
        return victim

    def _make_room(self, extra, exclude):
        evicted = []
        while self._bytes + extra > self.capacity_bytes:
            victim = self._victim_key(exclude)
            if victim is None:
                moved = False
                for protected_key in self._protected:
                    if exclude is None or protected_key != exclude:
                        self._demote(protected_key)
                        moved = True
                        break
                if not moved:
                    break
                victim = self._victim_key(exclude)
                if victim is None:
                    break
            evicted.append(self._remove_key(victim))
        return evicted

    def _promote(self, entry):
        if entry.segment != 0:
            return
        self._probationary.pop(entry.key, None)
        entry.segment = 1
        self._protected[entry.key] = entry
        self._protected_bytes += entry.size
        while self._protected_bytes > self._protected_target and self._protected:
            oldest = next(iter(self._protected))
            self._demote(oldest)

    def _demote(self, key):
        entry = self._protected.pop(key, None)
        if entry is None:
            return
        entry.segment = 0
        self._protected_bytes -= entry.size
        self._probationary[key] = entry

    def _remove_key(self, key):
        entry = self._entries.pop(key)
        if entry.segment == 0:
            self._probationary.pop(key, None)
        else:
            self._protected.pop(key, None)
            self._protected_bytes -= entry.size
        self._bytes -= entry.size
        self._remember(entry)
        return key

    def _remember(self, entry):
        self._discard_ghost(entry.key)
        self._ghost[entry.key] = (entry.segment, entry.size)
        self._ghost_bytes += entry.size
        while self._ghost and (self._ghost_bytes > self._ghost_byte_limit or len(self._ghost) > self._ghost_entry_limit):
            key, item = self._ghost.popitem(last=False)
            self._ghost_bytes -= item[1]

    def _discard_ghost(self, key):
        item = self._ghost.pop(key, None)
        if item is not None:
            self._ghost_bytes -= item[1]
        return item
