from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self._b1 = OrderedDict()
        self._b2 = OrderedDict()
        self._t1_bytes = 0
        self._t2_bytes = 0
        self._b1_bytes = 0
        self._b2_bytes = 0
        self._probation_target = 0

    def _remove_ghost(self, key):
        if key in self._b1:
            size = self._b1.pop(key)
            self._b1_bytes -= size
            return 1
        if key in self._b2:
            size = self._b2.pop(key)
            self._b2_bytes -= size
            return 2
        return 0

    def _remember_ghost(self, key, size, which):
        self._remove_ghost(key)
        if which == 1:
            self._b1[key] = size
            self._b1_bytes += size
        else:
            self._b2[key] = size
            self._b2_bytes += size
        while self._b1_bytes + self._b2_bytes > self.capacity_bytes:
            if self._b1 and (not self._b2 or self._b1_bytes >= self._b2_bytes):
                _, old_size = self._b1.popitem(last=False)
                self._b1_bytes -= old_size
            elif self._b2:
                _, old_size = self._b2.popitem(last=False)
                self._b2_bytes -= old_size
            else:
                break

    def _replace(self, incoming, size):
        evicted = []
        while self._t1_bytes + self._t2_bytes + size > self.capacity_bytes:
            choose_t1 = self.probation and (
                self._t1_bytes > self._probation_target
                or (incoming in self._b2 and self._t1_bytes == self._probation_target)
            )
            if choose_t1 or not self.protected:
                if not self.probation:
                    break
                old_key, old_size = self.probation.popitem(last=False)
                self._t1_bytes -= old_size
                self._remember_ghost(old_key, old_size, 1)
            else:
                old_key, old_size = self.protected.popitem(last=False)
                self._t2_bytes -= old_size
                self._remember_ghost(old_key, old_size, 2)
            evicted.append(old_key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self._t1_bytes -= stored_size
            self.protected[key] = stored_size
            self._t2_bytes += stored_size
            return []

        if self.capacity_bytes == 0 or size <= 0 or size > self.capacity_bytes:
            return []

        ghost_kind = self._remove_ghost(key)
        if ghost_kind == 1:
            if self._b1_bytes:
                delta = max(1, self._b2_bytes // self._b1_bytes)
            else:
                delta = self.capacity_bytes
            self._probation_target = min(
                self.capacity_bytes, self._probation_target + delta
            )
        elif ghost_kind == 2:
            if self._b2_bytes:
                delta = max(1, self._b1_bytes // self._b2_bytes)
            else:
                delta = self.capacity_bytes
            self._probation_target = max(
                0, self._probation_target - delta
            )

        evicted = self._replace(key, size)
        self.protected[key] = size
        self._t2_bytes += size
        if ghost_kind == 0:
            self.protected.pop(key)
            self._t2_bytes -= size
            self.probation[key] = size
            self._t1_bytes += size
        return evicted
