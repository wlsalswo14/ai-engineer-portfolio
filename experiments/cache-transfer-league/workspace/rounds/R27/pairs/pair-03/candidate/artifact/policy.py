from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.target_t1 = self.capacity_bytes // 2
        self.t1_bytes = 0
        self.t2_bytes = 0
        self.ghost_limit = 4096

    def _remember(self, ghost, key, size):
        self.b1.pop(key, None)
        self.b2.pop(key, None)
        ghost[key] = size
        while len(self.b1) + len(self.b2) > self.ghost_limit:
            if self.b1:
                self.b1.popitem(last=False)
            elif self.b2:
                self.b2.popitem(last=False)

    def _forget_ghost(self, key):
        self.b1.pop(key, None)
        self.b2.pop(key, None)

    def _replace(self, incoming_b2, evicted):
        choose_t1 = self.t1 and (
            self.t1_bytes > self.target_t1
            or (incoming_b2 and self.t1_bytes == self.target_t1)
        )
        if choose_t1:
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self._remember(self.b1, key, size)
        elif self.t2:
            key, size = self.t2.popitem(last=False)
            self.t2_bytes -= size
            self._remember(self.b2, key, size)
        elif self.t1:
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self._remember(self.b1, key, size)
        else:
            return False
        evicted.append(key)
        return True

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.t1:
            stored = self.t1.pop(key)
            self.t1_bytes -= stored
            self.t2[key] = stored
            self.t2_bytes += stored
            return []

        if key in self.t2:
            stored = self.t2.pop(key)
            self.t2[key] = stored
            return []

        if self.capacity_bytes <= 0 or size <= 0 or size > self.capacity_bytes:
            return []

        in_b1 = key in self.b1
        in_b2 = key in self.b2
        step = max(1, self.capacity_bytes // 16)
        if in_b1:
            self.target_t1 = min(
                self.capacity_bytes,
                self.target_t1 + max(step, self.b1[key]),
            )
        elif in_b2:
            self.target_t1 = max(
                0,
                self.target_t1 - max(step, self.b2[key]),
            )

        self._forget_ghost(key)
        evicted = []
        while self.t1_bytes + self.t2_bytes + size > self.capacity_bytes:
            if not self._replace(in_b2, evicted):
                return evicted

        self.t1[key] = size
        self.t1_bytes += size
        return evicted
