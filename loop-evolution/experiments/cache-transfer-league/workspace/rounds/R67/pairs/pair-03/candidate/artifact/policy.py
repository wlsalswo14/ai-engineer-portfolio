from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.t1_bytes = 0
        self.t2_bytes = 0
        self.b1_bytes = 0
        self.b2_bytes = 0
        self.used = 0
        self.target = self.capacity // 2
        self._serial = 0
        self._ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self._ghost_count_limit = 4096
        self._pending = None

    def _snapshot(self):
        return (OrderedDict(self.t1), OrderedDict(self.t2),
                OrderedDict(self.b1), OrderedDict(self.b2),
                self.t1_bytes, self.t2_bytes, self.b1_bytes,
                self.b2_bytes, self.used, self.target, self._serial)

    def _restore(self, state):
        (self.t1, self.t2, self.b1, self.b2, self.t1_bytes,
         self.t2_bytes, self.b1_bytes, self.b2_bytes, self.used,
         self.target, self._serial) = state

    def rollback_candidate_transition(self):
        if self._pending is None:
            return False
        self._restore(self._pending)
        self._pending = None
        return True

    def commit_candidate_transition(self):
        self._pending = None

    def _drop_ghost(self, key):
        value = self.b1.pop(key, None)
        if value is not None:
            self.b1_bytes -= value[0]
        value = self.b2.pop(key, None)
        if value is not None:
            self.b2_bytes -= value[0]

    def _trim_ghosts(self):
        while (self.b1_bytes + self.b2_bytes > self._ghost_limit or
               len(self.b1) + len(self.b2) > self._ghost_count_limit):
            first = None
            if self.b1:
                first = (1, next(iter(self.b1.values()))[1])
            if self.b2:
                candidate = (2, next(iter(self.b2.values()))[1])
                if first is None or candidate[1] < first[1]:
                    first = candidate
            ghosts = self.b1 if first[0] == 1 else self.b2
            _, value = ghosts.popitem(last=False)
            if first[0] == 1:
                self.b1_bytes -= value[0]
            else:
                self.b2_bytes -= value[0]

    def _remember_ghost(self, key, size, kind):
        self._drop_ghost(key)
        self._serial += 1
        value = (size, self._serial)
        if kind == 1:
            self.b1[key] = value
            self.b1_bytes += size
        else:
            self.b2[key] = value
            self.b2_bytes += size
        self._trim_ghosts()

    def _remove_resident(self, key):
        value = self.t1.pop(key, None)
        if value is not None:
            self.t1_bytes -= value
            self.used -= value
            return value, 1
        value = self.t2.pop(key, None)
        if value is not None:
            self.t2_bytes -= value
            self.used -= value
            return value, 2
        return 0, 0

    def _evict_one(self, prefer_t1):
        if prefer_t1 and self.t1:
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 1)
            return key
        if self.t2:
            key, size = self.t2.popitem(last=False)
            self.t2_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 2)
            return key
        if self.t1:
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 1)
            return key
        return None

    def _make_room(self, incoming, ghost_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            prefer_t1 = self.t1_bytes > self.target
            if ghost_kind == 1 and self.t1_bytes >= self.target:
                prefer_t1 = True
            if ghost_kind == 2 and self.t1_bytes == self.target:
                prefer_t1 = False
            key = self._evict_one(prefer_t1)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def _adapt_target(self, kind):
        if self.capacity <= 0:
            return
        if kind == 1:
            delta = self.capacity if self.b1_bytes == 0 else max(
                1, min(self.capacity, self.b2_bytes // self.b1_bytes or 1))
            self.target = min(self.capacity, self.target + delta)
        else:
            delta = self.capacity if self.b2_bytes == 0 else max(
                1, min(self.capacity, self.b1_bytes // self.b2_bytes or 1))
            self.target = max(0, self.target - delta)

    def access(self, key: int, size: int, now: int) -> list[int]:
        del now
        key = int(key)
        size = max(0, int(size))
        self._pending = None

        if key in self.t1 or key in self.t2:
            self._remove_resident(key)
            if size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            self._drop_ghost(key)
            self.t2[key] = size
            self.t2_bytes += size
            self.used += size
            return evicted

        ghost_kind = 1 if key in self.b1 else 2 if key in self.b2 else 0
        if size > self.capacity or (self.capacity == 0 and size == 0):
            return []

        if ghost_kind:
            self._pending = self._snapshot()
            self._adapt_target(ghost_kind)
            self._drop_ghost(key)

        evicted = self._make_room(size, ghost_kind)
        self.t2[key] = size if ghost_kind else size
        self.t2_bytes += size if ghost_kind else 0
        if not ghost_kind:
            self.t2.pop(key)
            self.t1[key] = size
            self.t1_bytes += size
        self.used += size
        return evicted
