from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.target_bytes = self.capacity_bytes // 2
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.t1_bytes = 0
        self.t2_bytes = 0
        self.ghost_bytes = 0
        self._resident = {}
        self._joint_representation = False

    @property
    def used_bytes(self):
        return self.t1_bytes + self.t2_bytes

    def _reconstitute(self):
        self._resident = {}
        for key, size in self.t1.items():
            self._resident[key] = (size, 1)
        for key, size in self.t2.items():
            self._resident[key] = (size, 2)
        self.t1_bytes = sum(self.t1.values())
        self.t2_bytes = sum(self.t2.values())
        self._joint_representation = True

    def _forget_ghost(self, key):
        if key in self.b1:
            size = self.b1.pop(key)
            self.ghost_bytes -= size
            return size, False
        if key in self.b2:
            size = self.b2.pop(key)
            self.ghost_bytes -= size
            return size, True
        return None, False

    def _remember_ghost(self, key, size, frequent):
        self._forget_ghost(key)
        ghost = self.b2 if frequent else self.b1
        ghost[key] = size
        self.ghost_bytes += size
        limit = max(1, self.capacity_bytes * 2)
        while self.ghost_bytes > limit:
            if self.b1:
                _, old_size = self.b1.popitem(last=False)
            elif self.b2:
                _, old_size = self.b2.popitem(last=False)
            else:
                break
            self.ghost_bytes -= old_size

    def _evict_one(self, from_t1):
        if from_t1 and self.t1:
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self._resident.pop(key, None)
            self._remember_ghost(key, size, False)
            return key
        if self.t2:
            key, size = self.t2.popitem(last=False)
            self.t2_bytes -= size
            self._resident.pop(key, None)
            self._remember_ghost(key, size, True)
            return key
        if self.t1:
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self._resident.pop(key, None)
            self._remember_ghost(key, size, False)
            return key
        return None

    def _replace(self, incoming_size, favor_recent):
        evicted = []
        while self.used_bytes + incoming_size > self.capacity_bytes:
            choose_t1 = bool(self.t1) and (
                self.t1_bytes > self.target_bytes
                or (favor_recent and self.t1_bytes == self.target_bytes)
                or not self.t2
            )
            key = self._evict_one(choose_t1)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def _adapt_step(self, size):
        return max(1, self.capacity_bytes // 16, min(self.capacity_bytes, size))

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.t1:
            stored_size = self.t1.pop(key)
            self.t1_bytes -= stored_size
            self.t2[key] = stored_size
            self.t2_bytes += stored_size
            self._resident[key] = (stored_size, 2)
            return []

        if key in self.t2:
            stored_size = self.t2.pop(key)
            self.t2[key] = stored_size
            self._resident[key] = (stored_size, 2)
            return []

        request_size = max(0, int(size))
        if self.capacity_bytes == 0 or request_size == 0 or request_size > self.capacity_bytes:
            return []

        if key in self.b1 or key in self.b2:
            if not self._joint_representation:
                self._reconstitute()
            old_size, in_b2 = self._forget_ghost(key)
            if in_b2:
                self.target_bytes = max(
                    0,
                    self.target_bytes - self._adapt_step(old_size or request_size),
                )
            else:
                self.target_bytes = min(
                    self.capacity_bytes,
                    self.target_bytes + self._adapt_step(old_size or request_size),
                )
            evicted = self._replace(request_size, not in_b2)
            self.t2[key] = request_size
            self.t2_bytes += request_size
            self._resident[key] = (request_size, 2)
            return evicted

        evicted = self._replace(request_size, False)
        self.t1[key] = request_size
        self.t1_bytes += request_size
        self._resident[key] = (request_size, 1)
        return evicted
