class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = int(capacity_bytes)
        if self.capacity < 0:
            self.capacity = 0
        self.t1 = {}
        self.t2 = {}
        self.b1 = {}
        self.b2 = {}
        self.t1_bytes = 0
        self.t2_bytes = 0
        self.b1_bytes = 0
        self.b2_bytes = 0
        self.resident_bytes = 0
        self.p = self.capacity // 2

    def _oldest(self, queue, exclude=None):
        for key in queue:
            if key != exclude:
                return key
        return None

    def _trim_ghosts(self):
        limit_bytes = self.capacity * 2
        while (self.b1_bytes + self.b2_bytes > limit_bytes or
               len(self.b1) + len(self.b2) > 8192):
            if self.b1 and (not self.b2 or self.b1_bytes >= self.b2_bytes):
                key, size = next(iter(self.b1.items()))
                del self.b1[key]
                self.b1_bytes -= size
            elif self.b2:
                key, size = next(iter(self.b2.items()))
                del self.b2[key]
                self.b2_bytes -= size
            else:
                break

    def _add_ghost(self, which, key, size):
        if which == 1:
            if key in self.b1:
                self.b1_bytes -= self.b1.pop(key)
            self.b1[key] = size
            self.b1_bytes += size
        else:
            if key in self.b2:
                self.b2_bytes -= self.b2.pop(key)
            self.b2[key] = size
            self.b2_bytes += size
        self._trim_ghosts()

    def _evict(self, which, key):
        if which == 1:
            size = self.t1.pop(key)
            self.t1_bytes -= size
            self.resident_bytes -= size
            self._add_ghost(1, key, size)
        else:
            size = self.t2.pop(key)
            self.t2_bytes -= size
            self.resident_bytes -= size
            self._add_ghost(2, key, size)
        return key

    def _replace(self, needed, incoming_b2=False, exclude=None):
        evicted = []
        while self.resident_bytes + needed > self.capacity:
            prefer_t1 = bool(self.t1) and (
                self.t1_bytes > self.p or
                (incoming_b2 and self.t1_bytes == self.p)
            )
            if prefer_t1:
                key = self._oldest(self.t1, exclude)
                if key is not None:
                    evicted.append(self._evict(1, key))
                    continue
                key = self._oldest(self.t2, exclude)
                if key is not None:
                    evicted.append(self._evict(2, key))
                    continue
            else:
                key = self._oldest(self.t2, exclude)
                if key is not None:
                    evicted.append(self._evict(2, key))
                    continue
                key = self._oldest(self.t1, exclude)
                if key is not None:
                    evicted.append(self._evict(1, key))
                    continue
            break
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        size = int(size)
        if size < 1:
            size = 1

        if key in self.t1 or key in self.t2:
            evicted = []
            if key in self.t1:
                old_size = self.t1[key]
                queue = self.t1
            else:
                old_size = self.t2[key]
                queue = self.t2

            delta = size - old_size
            if delta > 0:
                evicted.extend(self._replace(delta, False, key))
                if self.resident_bytes + delta > self.capacity:
                    which = 1 if key in self.t1 else 2
                    evicted.append(self._evict(which, key))
                    return evicted

            if delta:
                queue[key] = size
                if key in self.t1:
                    self.t1_bytes += delta
                else:
                    self.t2_bytes += delta
                self.resident_bytes += delta

            if key in self.t1:
                value = self.t1.pop(key)
                self.t1_bytes -= value
                self.t2[key] = value
                self.t2_bytes += value
            else:
                value = self.t2.pop(key)
                self.t2[key] = value
            return evicted

        if self.capacity == 0 or size > self.capacity:
            return []

        in_b1 = key in self.b1
        in_b2 = key in self.b2
        destination = 2 if (in_b1 or in_b2) else 1

        if in_b1:
            previous = self.b1_bytes
            self.b1_bytes -= self.b1.pop(key)
            delta = max(1, size, self.b2_bytes // max(1, previous))
            self.p = min(self.capacity, self.p + delta)
        elif in_b2:
            previous = self.b2_bytes
            self.b2_bytes -= self.b2.pop(key)
            delta = max(1, size, self.b1_bytes // max(1, previous))
            self.p = max(0, self.p - delta)

        evicted = self._replace(size, in_b2)
        if self.resident_bytes + size > self.capacity:
            return evicted

        if destination == 1:
            self.t1[key] = size
            self.t1_bytes += size
        else:
            self.t2[key] = size
            self.t2_bytes += size
        self.resident_bytes += size
        return evicted
