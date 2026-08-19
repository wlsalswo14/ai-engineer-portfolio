from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        self.capacity = max(0, int(capacity_bytes))
        self.probationary = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probationary = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.probationary_bytes = 0
        self.protected_bytes = 0
        self.used = 0
        self.target_probationary = self.capacity // 2
        self.ghost_bytes = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096
        self.serial = 0

    def _forget_ghost(self, key):
        value = self.ghost_probationary.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]
        value = self.ghost_protected.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, kind):
        self._forget_ghost(key)
        self.serial += 1
        value = (max(1, int(size)), self.serial)
        if kind == 1:
            self.ghost_probationary[key] = value
        else:
            self.ghost_protected[key] = value
        self.ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_probationary) + len(self.ghost_protected) > self.ghost_count_limit):
            oldest_key = None
            oldest_bucket = None
            oldest_stamp = None
            for bucket in (self.ghost_probationary, self.ghost_protected):
                if bucket:
                    key = next(iter(bucket))
                    stamp = bucket[key][1]
                    if oldest_stamp is None or stamp < oldest_stamp:
                        oldest_key = key
                        oldest_bucket = bucket
                        oldest_stamp = stamp
            if oldest_bucket is None:
                break
            value = oldest_bucket.pop(oldest_key)
            self.ghost_bytes -= value[0]

    def _adapt(self, kind):
        if self.capacity <= 0:
            return
        b1 = sum(value[0] for value in self.ghost_probationary.values())
        b2 = sum(value[0] for value in self.ghost_protected.values())
        if kind == 1:
            delta = self.capacity if b1 == 0 else max(1, min(self.capacity, b2 // b1 or 1))
            self.target_probationary = min(self.capacity, self.target_probationary + delta)
        else:
            delta = self.capacity if b2 == 0 else max(1, min(self.capacity, b1 // b2 or 1))
            self.target_probationary = max(0, self.target_probationary - delta)

    def _remove_resident(self, key):
        value = self.probationary.pop(key, None)
        if value is not None:
            self.probationary_bytes -= value
            self.used -= value
            return value
        value = self.protected.pop(key, None)
        if value is not None:
            self.protected_bytes -= value
            self.used -= value
            return value
        return None

    def _evict_one(self, prefer_probationary):
        if prefer_probationary and self.probationary:
            key, size = self.probationary.popitem(last=False)
            self.probationary_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 1)
            return key
        if self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 2)
            return key
        if self.probationary:
            key, size = self.probationary.popitem(last=False)
            self.probationary_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 1)
            return key
        return None

    def _make_room(self, incoming, ghost_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            prefer_probationary = self.probationary_bytes > self.target_probationary
            if ghost_kind == 2 and self.probationary_bytes == self.target_probationary:
                prefer_probationary = True
            key = self._evict_one(prefer_probationary)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key, size, now):
        key = int(key)
        size = max(0, int(size))

        if key in self.probationary or key in self.protected:
            self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            if self.used + size > self.capacity:
                return evicted + [key]
            self._forget_ghost(key)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            return evicted

        ghost_kind = 1 if key in self.ghost_probationary else 2 if key in self.ghost_protected else 0
        if size <= 0 or size > self.capacity:
            return []
        if ghost_kind:
            self._adapt(ghost_kind)
            self._forget_ghost(key)

        evicted = self._make_room(size, ghost_kind)
        if self.used + size > self.capacity:
            return evicted
        if ghost_kind == 2 or ghost_kind == 1:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.probationary[key] = size
            self.probationary_bytes += size
        self.used += size
        return evicted
