from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.t1_bytes = 0
        self.t2_bytes = 0
        self.p = 0
        self.ghost_limit = 4096

    def _remember(self, ghost, key):
        ghost.pop(key, None)
        ghost[key] = None
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _forget(self, key):
        self.b1.pop(key, None)
        self.b2.pop(key, None)

    def _adjust_target(self, size, in_b1):
        delta = max(1, self.capacity_bytes // 16)
        if size > 0:
            delta = max(delta, min(size, self.capacity_bytes))
        if in_b1:
            self.p = min(self.capacity_bytes, self.p + delta)
        else:
            self.p = max(0, self.p - delta)

    def _replace(self, incoming_in_b2):
        if self.t1 and (self.t1_bytes > self.p or (incoming_in_b2 and self.t1_bytes == self.p)):
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self._remember(self.b1, key)
            return key
        if self.t2:
            key, size = self.t2.popitem(last=False)
            self.t2_bytes -= size
            self._remember(self.b2, key)
            return key
        if self.t1:
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self._remember(self.b1, key)
            return key
        return None

    def access(self, key: int, size: int, now: int) -> list[int]:
        _ = now

        if key in self.t1:
            stored_size = self.t1.pop(key)
            self.t1_bytes -= stored_size
            self.t2[key] = stored_size
            self.t2_bytes += stored_size
            return []

        if key in self.t2:
            stored_size = self.t2.pop(key)
            self.t2[key] = stored_size
            return []

        if size <= 0 or size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        in_b1 = key in self.b1
        in_b2 = key in self.b2
        if in_b1 or in_b2:
            self._adjust_target(size, in_b1)
        self._forget(key)

        evicted = []
        while self.t1_bytes + self.t2_bytes + size > self.capacity_bytes:
            old_key = self._replace(in_b2)
            if old_key is None:
                break
            evicted.append(old_key)

        self.t1[key] = size
        self.t1_bytes += size
        return evicted
