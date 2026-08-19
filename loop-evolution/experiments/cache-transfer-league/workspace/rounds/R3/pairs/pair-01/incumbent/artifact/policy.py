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
        self.b1_bytes = 0
        self.b2_bytes = 0
        self.used_bytes = 0
        self.target_t1_bytes = 0

    def _remove_ghost(self, key):
        if key in self.b1:
            size = self.b1.pop(key)
            self.b1_bytes -= size
            return size
        if key in self.b2:
            size = self.b2.pop(key)
            self.b2_bytes -= size
            return size
        return None

    def _add_ghost(self, ghost, key, size):
        self._remove_ghost(key)
        ghost[key] = size
        if ghost is self.b1:
            self.b1_bytes += size
            while self.b1 and self.b1_bytes > self.capacity_bytes:
                _, old_size = self.b1.popitem(last=False)
                self.b1_bytes -= old_size
        else:
            self.b2_bytes += size
            while self.b2 and self.b2_bytes > self.capacity_bytes:
                _, old_size = self.b2.popitem(last=False)
                self.b2_bytes -= old_size

    def _replace(self, incoming_size, prefer_t2=False):
        evicted = []
        while self.used_bytes + incoming_size > self.capacity_bytes:
            if self.t1 and (
                self.t1_bytes > self.target_t1_bytes
                or (prefer_t2 and self.t1_bytes == self.target_t1_bytes)
            ):
                key, size = self.t1.popitem(last=False)
                self.t1_bytes -= size
                self.used_bytes -= size
                self._add_ghost(self.b1, key, size)
                evicted.append(key)
            elif self.t2:
                key, size = self.t2.popitem(last=False)
                self.t2_bytes -= size
                self.used_bytes -= size
                self._add_ghost(self.b2, key, size)
                evicted.append(key)
            elif self.t1:
                key, size = self.t1.popitem(last=False)
                self.t1_bytes -= size
                self.used_bytes -= size
                self._add_ghost(self.b1, key, size)
                evicted.append(key)
            else:
                break
        return evicted

    def _insert(self, target, key, size):
        target[key] = size
        if target is self.t1:
            self.t1_bytes += size
        else:
            self.t2_bytes += size
        self.used_bytes += size

    def access(self, key: int, size: int, now: int) -> list[int]:
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

        incoming_size = max(0, size)
        if self.capacity_bytes == 0 or incoming_size > self.capacity_bytes:
            return []

        in_b1 = key in self.b1
        in_b2 = key in self.b2

        if in_b1:
            denominator = max(1, self.b1_bytes)
            increase = max(1, self.b2_bytes // denominator)
            self.target_t1_bytes = min(
                self.capacity_bytes,
                self.target_t1_bytes + increase,
            )
            self._remove_ghost(key)
            evicted = self._replace(incoming_size, prefer_t2=True)
            self._insert(self.t2, key, incoming_size)
            return evicted

        if in_b2:
            denominator = max(1, self.b2_bytes)
            decrease = max(1, self.b1_bytes // denominator)
            self.target_t1_bytes = max(
                0,
                self.target_t1_bytes - decrease,
            )
            self._remove_ghost(key)
            evicted = self._replace(incoming_size, prefer_t2=False)
            self._insert(self.t2, key, incoming_size)
            return evicted

        evicted = self._replace(incoming_size, prefer_t2=False)
        self._insert(self.t1, key, incoming_size)
        return evicted
