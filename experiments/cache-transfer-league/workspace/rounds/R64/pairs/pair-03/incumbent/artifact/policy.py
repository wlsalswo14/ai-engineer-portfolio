from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self._target = self.capacity_bytes // 2
        self._bytes = 0
        self._protected_bytes = 0
        self._probationary = OrderedDict()
        self._protected = OrderedDict()
        self._meta = {}
        self._ghost = OrderedDict()
        self._ghost_limit = max(64, min(8192, 64 + self.capacity_bytes // 64))
        self._tick = 0

    def _remember(self, key, segment):
        if key in self._ghost:
            del self._ghost[key]
        self._ghost[key] = segment
        while len(self._ghost) > self._ghost_limit:
            self._ghost.popitem(last=False)

    def _adjust_target(self, segment, weight):
        step = max(1, self.capacity_bytes // 16)
        delta = max(step, weight)
        if segment == 0:
            self._target = max(0, self._target - delta)
        else:
            self._target = min(self.capacity_bytes, self._target + delta)

    def _drop(self, key, remember_segment=None):
        entry = self._meta.pop(key)
        weight = entry[0]
        if key in self._probationary:
            del self._probationary[key]
            self._bytes -= weight
        elif key in self._protected:
            del self._protected[key]
            self._protected_bytes -= weight
            self._bytes -= weight
        if remember_segment is not None:
            self._remember(key, remember_segment)
        return [key]

    def _trim(self):
        evicted = []
        while self._protected_bytes > self._target and self._protected:
            key, entry = self._protected.popitem(last=False)
            self._protected_bytes -= entry[0]
            self._probationary[key] = None
            self._probationary.move_to_end(key, last=False)
        while self._bytes > self.capacity_bytes:
            if self._probationary:
                key, entry = self._probationary.popitem(last=False)
                segment = 0
            elif self._protected:
                key, entry = self._protected.popitem(last=False)
                self._protected_bytes -= entry[0]
                segment = 1
            else:
                break
            self._meta.pop(key, None)
            self._bytes -= entry[0]
            self._remember(key, segment)
            evicted.append(key)
        return evicted

    def access(self, key, size, now):
        self._tick += 1
        weight = max(0, int(size))

        if key in self._meta:
            if self.capacity_bytes == 0 or weight > self.capacity_bytes:
                return self._drop(key)
            entry = self._meta[key]
            old_weight = entry[0]
            if weight != old_weight:
                entry[0] = weight
                self._bytes += weight - old_weight
                if key in self._protected:
                    self._protected_bytes += weight - old_weight
            entry[1] = min(entry[1] + 1, 1073741824)
            entry[2] = self._tick
            if key in self._probationary:
                del self._probationary[key]
                self._protected[key] = None
                self._protected_bytes += weight
            else:
                self._protected.move_to_end(key)
            return self._trim()

        if self.capacity_bytes == 0 or weight > self.capacity_bytes:
            return []

        if key in self._ghost:
            segment = self._ghost.pop(key)
            self._adjust_target(segment, weight)

        self._meta[key] = [weight, 1, self._tick]
        self._probationary[key] = None
        self._bytes += weight
        return self._trim()
