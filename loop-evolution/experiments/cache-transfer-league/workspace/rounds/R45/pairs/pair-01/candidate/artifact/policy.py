from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        try:
            capacity = int(capacity_bytes)
        except (TypeError, ValueError, OverflowError):
            capacity = 0
        self.capacity = max(0, capacity)
        self._p = 0
        self._t1 = OrderedDict()
        self._t2 = OrderedDict()
        self._b1 = OrderedDict()
        self._b2 = OrderedDict()
        self._t1_bytes = 0
        self._t2_bytes = 0
        self._bytes = 0
        self._ghost_limit = 4096

    def _ghost_add(self, queue, key, size):
        self._b1.pop(key, None)
        self._b2.pop(key, None)
        queue[key] = size
        while len(self._b1) + len(self._b2) > self._ghost_limit:
            if self._b1 and (not self._b2 or len(self._b1) >= len(self._b2)):
                self._b1.popitem(last=False)
            elif self._b2:
                self._b2.popitem(last=False)
            else:
                break

    def _take(self, queue):
        key, size = queue.popitem(last=False)
        if queue is self._t1:
            self._t1_bytes -= size
            ghost = self._b1
        else:
            self._t2_bytes -= size
            ghost = self._b2
        self._bytes -= size
        self._ghost_add(ghost, key, size)
        return key

    def _make_room(self, need, from_b2=False):
        evicted = []
        while self._bytes + need > self.capacity and (self._t1 or self._t2):
            if self._t1 and (self._t1_bytes > self._p or (from_b2 and self._t1_bytes == self._p)):
                evicted.append(self._take(self._t1))
            elif self._t2:
                evicted.append(self._take(self._t2))
            elif self._t1:
                evicted.append(self._take(self._t1))
        return evicted

    def _drain(self):
        evicted = []
        while self._t1:
            evicted.append(self._take(self._t1))
        while self._t2:
            evicted.append(self._take(self._t2))
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        try:
            n = int(size)
        except (TypeError, ValueError, OverflowError):
            return []

        if self.capacity <= 0:
            return self._drain()
        if n <= 0:
            return []
        if n > self.capacity:
            return self._drain()

        if key in self._t1:
            old = self._t1.pop(key)
            self._t1_bytes -= old
            self._bytes -= old
            self._b1.pop(key, None)
            self._b2.pop(key, None)
            evicted = self._make_room(n)
            self._t2[key] = n
            self._t2_bytes += n
            self._bytes += n
            return evicted

        if key in self._t2:
            old = self._t2.pop(key)
            self._t2_bytes -= old
            self._bytes -= old
            self._b1.pop(key, None)
            self._b2.pop(key, None)
            evicted = self._make_room(n)
            self._t2[key] = n
            self._t2_bytes += n
            self._bytes += n
            return evicted

        in_b1 = key in self._b1
        in_b2 = key in self._b2
        if in_b1:
            self._b1.pop(key, None)
            self._p = min(self.capacity, self._p + max(1, min(n, self.capacity)))
        elif in_b2:
            self._b2.pop(key, None)
            self._p = max(0, self._p - max(1, min(n, self.capacity)))

        evicted = self._make_room(n, from_b2=in_b2)
        if in_b1 or in_b2:
            self._t2[key] = n
            self._t2_bytes += n
        else:
            self._t1[key] = n
            self._t1_bytes += n
        self._bytes += n
        return evicted
