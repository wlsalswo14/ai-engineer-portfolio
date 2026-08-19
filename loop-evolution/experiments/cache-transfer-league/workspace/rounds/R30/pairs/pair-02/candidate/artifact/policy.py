from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.t1_bytes = 0
        self.t2_bytes = 0
        self.b1_bytes = 0
        self.b2_bytes = 0
        self.used_bytes = 0
        self.p = self.capacity_bytes // 4
        self.ghost_limit = max(64, min(8192, self.capacity_bytes // 64 + 64))

    def _drop_ghost(self, key):
        value = self.b1.pop(key, None)
        if value is not None:
            self.b1_bytes -= value
        value = self.b2.pop(key, None)
        if value is not None:
            self.b2_bytes -= value

    def _trim_ghosts(self):
        while len(self.b1) > self.ghost_limit:
            _, value = self.b1.popitem(last=False)
            self.b1_bytes -= value
        while len(self.b2) > self.ghost_limit:
            _, value = self.b2.popitem(last=False)
            self.b2_bytes -= value

    def _remember(self, ghost, key, size):
        self._drop_ghost(key)
        ghost[key] = size
        if ghost is self.b1:
            self.b1_bytes += size
        else:
            self.b2_bytes += size
        self._trim_ghosts()

    def _evict_from(self, cache, ghost, avoid):
        victim = next((key for key in cache if key != avoid), None)
        if victim is None:
            return None
        size = cache.pop(victim)
        if cache is self.t1:
            self.t1_bytes -= size
        else:
            self.t2_bytes -= size
        self.used_bytes -= size
        self._remember(ghost, victim, size)
        return victim

    def _replace(self, incoming_b2=False, avoid=None):
        prefer_t1 = bool(self.t1) and (
            self.t1_bytes > self.p
            or (incoming_b2 and self.t1_bytes == self.p)
        )
        if prefer_t1:
            victim = self._evict_from(self.t1, self.b1, avoid)
            if victim is not None:
                return victim
            return self._evict_from(self.t2, self.b2, avoid)
        victim = self._evict_from(self.t2, self.b2, avoid)
        if victim is not None:
            return victim
        return self._evict_from(self.t1, self.b1, avoid)

    def _make_room(self, required, incoming_b2=False, avoid=None):
        evicted = []
        while self.used_bytes + required > self.capacity_bytes:
            victim = self._replace(incoming_b2=incoming_b2, avoid=avoid)
            if victim is None:
                break
            evicted.append(victim)
        return evicted

    def _change_size(self, key, size, cache, ghost):
        old_size = cache[key]
        if size <= 0 or size > self.capacity_bytes:
            cache.pop(key)
            if cache is self.t1:
                self.t1_bytes -= old_size
            else:
                self.t2_bytes -= old_size
            self.used_bytes -= old_size
            self._remember(ghost, key, old_size)
            return [key]
        delta = size - old_size
        if delta > 0:
            evicted = self._make_room(delta, avoid=key)
            if self.used_bytes + delta > self.capacity_bytes:
                cache.pop(key)
                if cache is self.t1:
                    self.t1_bytes -= old_size
                else:
                    self.t2_bytes -= old_size
                self.used_bytes -= old_size
                self._remember(ghost, key, old_size)
                return evicted + [key]
            self.used_bytes += delta
        else:
            self.used_bytes += delta
        cache[key] = size
        if cache is self.t1:
            self.t1_bytes += delta
        else:
            self.t2_bytes += delta
        return evicted if delta > 0 else []

    def access(self, key: int, size: int, now: int) -> list[int]:
        size = int(size)

        if key in self.t2:
            self.t2.move_to_end(key)
            return self._change_size(key, size, self.t2, self.b2)

        if key in self.t1:
            old_size = self.t1.pop(key)
            self.t1_bytes -= old_size
            self.t2[key] = old_size
            self.t2_bytes += old_size
            return self._change_size(key, size, self.t2, self.b2)

        if self.capacity_bytes <= 0 or size <= 0 or size > self.capacity_bytes:
            return []

        from_b1 = key in self.b1
        from_b2 = key in self.b2
        if from_b1:
            ratio = max(1, self.b2_bytes // max(1, self.b1_bytes))
            delta = max(1, min(self.capacity_bytes, max(size, ratio)))
            self.p = min(self.capacity_bytes, self.p + delta)
            self._drop_ghost(key)
        elif from_b2:
            ratio = max(1, self.b1_bytes // max(1, self.b2_bytes))
            delta = max(1, min(self.capacity_bytes, max(size, ratio)))
            self.p = max(0, self.p - delta)
            self._drop_ghost(key)

        evicted = self._make_room(size, incoming_b2=from_b2)
        if self.used_bytes + size > self.capacity_bytes:
            return evicted

        if from_b1 or from_b2:
            self.t2[key] = size
            self.t2_bytes += size
        else:
            self.t1[key] = size
            self.t1_bytes += size
        self.used_bytes += size
        return evicted
