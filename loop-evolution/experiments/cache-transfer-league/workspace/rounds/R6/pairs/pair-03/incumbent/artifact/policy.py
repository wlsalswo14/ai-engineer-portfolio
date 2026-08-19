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
        self.target_t1_bytes = self.capacity_bytes // 2

    def _forget_ghost(self, key):
        if key in self.b1:
            self.b1_bytes -= self.b1.pop(key)
            return
        if key in self.b2:
            self.b2_bytes -= self.b2.pop(key)

    def _remember(self, ghost, key, size):
        self._forget_ghost(key)
        ghost[key] = size
        if ghost is self.b1:
            self.b1_bytes += size
            while self.b1_bytes > self.capacity_bytes and self.b1:
                old_key, old_size = self.b1.popitem(last=False)
                self.b1_bytes -= old_size
        else:
            self.b2_bytes += size
            while self.b2_bytes > self.capacity_bytes and self.b2:
                old_key, old_size = self.b2.popitem(last=False)
                self.b2_bytes -= old_size

    def _replace(self, incoming_size):
        evicted = []
        while self.used_bytes + incoming_size > self.capacity_bytes:
            choose_t1 = bool(self.t1) and (
                self.t1_bytes > self.target_t1_bytes
                or (self.t1_bytes == self.target_t1_bytes and not self.t2)
            )
            if choose_t1 or not self.t2:
                if not self.t1:
                    break
                old_key, old_size = self.t1.popitem(last=False)
                self.t1_bytes -= old_size
                self.used_bytes -= old_size
                self._remember(self.b1, old_key, old_size)
            else:
                old_key, old_size = self.t2.popitem(last=False)
                self.t2_bytes -= old_size
                self.used_bytes -= old_size
                self._remember(self.b2, old_key, old_size)
            evicted.append(old_key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.t2:
            stored_size = self.t2.pop(key)
            self.t2[key] = stored_size
            return []

        if key in self.t1:
            stored_size = self.t1.pop(key)
            self.t1_bytes -= stored_size
            self.t2[key] = stored_size
            self.t2_bytes += stored_size
            return []

        if self.capacity_bytes == 0 or size < 0 or size > self.capacity_bytes:
            return []

        in_b1 = key in self.b1
        in_b2 = key in self.b2
        if in_b1:
            self.target_t1_bytes = min(
                self.capacity_bytes,
                self.target_t1_bytes + max(1, min(size, self.capacity_bytes)),
            )
        elif in_b2:
            self.target_t1_bytes = max(
                0,
                self.target_t1_bytes - max(1, min(size, self.capacity_bytes)),
            )

        if in_b1 or in_b2:
            self._forget_ghost(key)
            evicted = self._replace(size)
            self.t2[key] = size
            self.t2_bytes += size
        else:
            evicted = self._replace(size)
            self.t1[key] = size
            self.t1_bytes += size

        self.used_bytes += size
        return evicted
