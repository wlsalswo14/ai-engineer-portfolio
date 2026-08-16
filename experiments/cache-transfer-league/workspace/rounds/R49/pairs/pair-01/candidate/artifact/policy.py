from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        try:
            capacity = int(capacity_bytes)
        except (TypeError, ValueError, OverflowError):
            capacity = 0
        self.capacity_bytes = max(0, capacity)
        self._probationary = OrderedDict()
        self._protected = OrderedDict()
        self._b1 = OrderedDict()
        self._b2 = OrderedDict()
        self._probationary_bytes = 0
        self._protected_bytes = 0
        self._resident_bytes = 0
        self._protected_target = self.capacity_bytes // 2
        self._tick = 0
        self._ghost_limit = 4096

    def _remember(self, ghost, key, size):
        self._b1.pop(key, None)
        self._b2.pop(key, None)
        ghost[key] = size
        while len(ghost) > self._ghost_limit:
            ghost.popitem(last=False)

    def _remove_resident(self, key):
        item = self._probationary.pop(key, None)
        if item is not None:
            self._probationary_bytes -= item[0]
            self._resident_bytes -= item[0]
            return 'probationary', item
        item = self._protected.pop(key, None)
        if item is not None:
            self._protected_bytes -= item[0]
            self._resident_bytes -= item[0]
            return 'protected', item
        return None, None

    def _trim_protected(self):
        while self._protected and self._protected_bytes > self._protected_target:
            key, item = self._protected.popitem(last=False)
            self._protected_bytes -= item[0]
            self._probationary[key] = item
            self._probationary_bytes += item[0]

    def _evict_one(self):
        if self._probationary and (
            self._probationary_bytes > self._protected_target
            or not self._protected
        ):
            key, item = self._probationary.popitem(last=False)
            self._probationary_bytes -= item[0]
            self._resident_bytes -= item[0]
            self._remember(self._b1, key, item[0])
            return key
        if self._protected:
            key, item = self._protected.popitem(last=False)
            self._protected_bytes -= item[0]
            self._resident_bytes -= item[0]
            self._remember(self._b2, key, item[0])
            return key
        if self._probationary:
            key, item = self._probationary.popitem(last=False)
            self._probationary_bytes -= item[0]
            self._resident_bytes -= item[0]
            self._remember(self._b1, key, item[0])
            return key
        return None

    def _enforce_capacity(self):
        self._trim_protected()
        evicted = []
        while self._resident_bytes > self.capacity_bytes:
            key = self._evict_one()
            if key is None:
                break
            evicted.append(key)
        return evicted

    def _age(self):
        if self._tick % 256:
            return
        for mapping in (self._probationary, self._protected):
            for item in mapping.values():
                item[1] = max(1, item[1] // 2)

    def access(self, key, size, now):
        if isinstance(key, bool) or not isinstance(key, int):
            return []
        try:
            requested = int(size)
        except (TypeError, ValueError, OverflowError):
            return []
        if requested <= 0:
            return []

        self._tick += 1
        self._age()

        if key in self._probationary:
            item = self._probationary.pop(key)
            old_size = item[0]
            self._probationary_bytes -= old_size
            self._resident_bytes += requested - old_size
            item[0] = requested
            item[1] = min(255, item[1] + 1)
            item[2] = self._tick
            self._protected[key] = item
            self._protected_bytes += requested
            if requested > self.capacity_bytes:
                self._protected.pop(key, None)
                self._protected_bytes -= requested
                self._resident_bytes -= requested
                self._remember(self._b2, key, requested)
                return [key]
            return self._enforce_capacity()

        if key in self._protected:
            item = self._protected.pop(key)
            old_size = item[0]
            self._protected_bytes -= old_size
            self._resident_bytes += requested - old_size
            item[0] = requested
            item[1] = min(255, item[1] + 1)
            item[2] = self._tick
            self._protected[key] = item
            self._protected_bytes += requested
            if requested > self.capacity_bytes:
                self._protected.pop(key, None)
                self._protected_bytes -= requested
                self._resident_bytes -= requested
                self._remember(self._b2, key, requested)
                return [key]
            return self._enforce_capacity()

        if requested > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        if key in self._b1:
            self._b1.pop(key, None)
            self._protected_target = min(
                self.capacity_bytes,
                self._protected_target + max(1, min(requested, self.capacity_bytes // 8 or 1)),
            )
            segment = self._protected
            self._protected_bytes += requested
            frequency = 2
        elif key in self._b2:
            self._b2.pop(key, None)
            self._protected_target = max(
                0,
                self._protected_target - max(1, min(requested, self.capacity_bytes // 8 or 1)),
            )
            segment = self._protected
            self._protected_bytes += requested
            frequency = 2
        else:
            segment = self._probationary
            self._probationary_bytes += requested
            frequency = 1

        segment[key] = [requested, frequency, self._tick]
        self._resident_bytes += requested
        return self._enforce_capacity()
