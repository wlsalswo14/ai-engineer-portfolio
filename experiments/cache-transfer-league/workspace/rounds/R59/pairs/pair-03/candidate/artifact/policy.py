from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        try:
            capacity = int(capacity_bytes)
        except Exception:
            capacity = 0
        self.capacity = max(0, capacity)
        self.used = 0
        self.clock = 0
        self.items = {}
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.g1 = OrderedDict()
        self.g2 = OrderedDict()
        self.t1_bytes = 0
        self.t2_bytes = 0
        self.g1_bytes = 0
        self.g2_bytes = 0
        self.target = 0

    def _size(self, value):
        try:
            return int(value)
        except Exception:
            return 0

    def _discard_ghost(self, key):
        value = self.g1.pop(key, None)
        if value is not None:
            self.g1_bytes -= value[0]
        value = self.g2.pop(key, None)
        if value is not None:
            self.g2_bytes -= value[0]

    def _add_ghost(self, which, key, size):
        self._discard_ghost(key)
        value = (size, self.clock)
        if which == 1:
            self.g1[key] = value
            self.g1_bytes += size
        else:
            self.g2[key] = value
            self.g2_bytes += size
        limit = max(1, self.capacity)
        while self.g1_bytes + self.g2_bytes > limit:
            first1 = next(iter(self.g1), None)
            first2 = next(iter(self.g2), None)
            if first1 is None:
                key_to_drop = first2
                queue = self.g2
            elif first2 is None:
                key_to_drop = first1
                queue = self.g1
            elif self.g1[first1][1] <= self.g2[first2][1]:
                key_to_drop = first1
                queue = self.g1
            else:
                key_to_drop = first2
                queue = self.g2
            dropped = queue.pop(key_to_drop)
            if queue is self.g1:
                self.g1_bytes -= dropped[0]
            else:
                self.g2_bytes -= dropped[0]

    def _remove_resident(self, key, ghost=None):
        entry = self.items.pop(key, None)
        if entry is None:
            return False
        size = entry['size']
        self.used -= size
        if key in self.t1:
            self.t1.pop(key, None)
            self.t1_bytes -= size
        if key in self.t2:
            self.t2.pop(key, None)
            self.t2_bytes -= size
        if ghost is not None:
            self._add_ghost(ghost, key, size)
        return True

    def _choose_victim(self, protected):
        prefer_t1 = bool(self.t1) and (self.t1_bytes >= self.target or not self.t2)
        queues = (self.t1, self.t2) if prefer_t1 else (self.t2, self.t1)
        for queue in queues:
            for key in queue:
                if key not in protected:
                    return key
        return None

    def _trim(self, evicted, protected):
        while self.used > self.capacity:
            victim = self._choose_victim(protected)
            if victim is None:
                break
            entry = self.items.get(victim)
            if entry is None:
                continue
            ghost = 1 if victim in self.t1 else 2
            self._remove_resident(victim, ghost)
            evicted.append(victim)

    def access(self, key, size, now):
        self.clock += 1
        del now
        evicted = []
        if not isinstance(key, int) or isinstance(key, bool):
            return evicted
        requested = self._size(size)

        if key in self.items:
            if requested <= 0 or requested > self.capacity:
                self._remove_resident(key)
                self._discard_ghost(key)
                evicted.append(key)
                return evicted
            entry = self.items[key]
            old_size = entry['size']
            if requested != old_size:
                self.used += requested - old_size
                entry['size'] = requested
                if key in self.t1:
                    self.t1_bytes += requested - old_size
                else:
                    self.t2_bytes += requested - old_size
            entry['frequency'] += 1
            entry['stamp'] = self.clock
            if key in self.t1:
                self.t1.pop(key, None)
                self.t1_bytes -= requested
                self.t2[key] = None
                self.t2_bytes += requested
            else:
                self.t2.move_to_end(key)
            self._trim(evicted, {key})
            return evicted

        if requested <= 0 or requested > self.capacity:
            self._discard_ghost(key)
            return evicted

        if key in self.g1:
            self.target = min(self.capacity, self.target + max(1, min(self.capacity, requested)))
            self._discard_ghost(key)
        elif key in self.g2:
            self.target = max(0, self.target - max(1, min(self.capacity, requested)))
            self._discard_ghost(key)

        self.items[key] = {
            'size': requested,
            'frequency': 1,
            'stamp': self.clock,
        }
        self.t1[key] = None
        self.t1_bytes += requested
        self.used += requested
        self._trim(evicted, {key})
        return evicted
