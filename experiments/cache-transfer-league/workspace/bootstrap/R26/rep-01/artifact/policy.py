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
        self.used_bytes = 0
        self.target_bytes = self.capacity_bytes // 2
        self.ghost_bytes = 0
        self.ghost_clock = 0
        self.ghost_limit = max(1, self.capacity_bytes)

    def _remove_ghost(self, key):
        if key in self.b1:
            size, _ = self.b1.pop(key)
            self.ghost_bytes -= size
            return 1
        if key in self.b2:
            size, _ = self.b2.pop(key)
            self.ghost_bytes -= size
            return 2
        return 0

    def _add_ghost(self, queue, key, size):
        self._remove_ghost(key)
        self.ghost_clock += 1
        queue[key] = (size, self.ghost_clock)
        self.ghost_bytes += size
        while self.ghost_bytes > self.capacity_bytes or len(self.b1) + len(self.b2) > self.ghost_limit:
            first = next(iter(self.b1.items()), None)
            second = next(iter(self.b2.items()), None)
            if first is None:
                old_queue = self.b2
            elif second is None:
                old_queue = self.b1
            elif first[1][1] <= second[1][1]:
                old_queue = self.b1
            else:
                old_queue = self.b2
            _, (old_size, _) = old_queue.popitem(last=False)
            self.ghost_bytes -= old_size

    def _rebalance(self):
        while self.t2 and self.t2_bytes > self.target_bytes:
            key, size = self.t2.popitem(last=False)
            self.t2_bytes -= size
            self.t1[key] = size
            self.t1_bytes += size

    def _make_room(self, size, evicted):
        while self.used_bytes + size > self.capacity_bytes:
            if self.t1 and (self.t1_bytes >= self.capacity_bytes - self.target_bytes or not self.t2):
                key, stored = self.t1.popitem(last=False)
                self.t1_bytes -= stored
                self.used_bytes -= stored
                self._add_ghost(self.b1, key, stored)
            elif self.t2:
                key, stored = self.t2.popitem(last=False)
                self.t2_bytes -= stored
                self.used_bytes -= stored
                self._add_ghost(self.b2, key, stored)
            elif self.t1:
                key, stored = self.t1.popitem(last=False)
                self.t1_bytes -= stored
                self.used_bytes -= stored
                self._add_ghost(self.b1, key, stored)
            else:
                break
            evicted.append(key)

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.t2:
            stored = self.t2.pop(key)
            self.t2[key] = stored
            return []

        if key in self.t1:
            stored = self.t1.pop(key)
            self.t1_bytes -= stored
            if self.target_bytes > 0 and stored <= self.target_bytes:
                self.t2[key] = stored
                self.t2_bytes += stored
                self._rebalance()
            else:
                self.t1[key] = stored
                self.t1_bytes += stored
            return []

        if size > self.capacity_bytes:
            return []

        ghost_kind = self._remove_ghost(key)
        if ghost_kind == 1:
            self.target_bytes = min(self.capacity_bytes, self.target_bytes + max(1, size))
        elif ghost_kind == 2:
            self.target_bytes = max(0, self.target_bytes - max(1, size))
            self._rebalance()

        evicted = []
        self._make_room(size, evicted)

        if ghost_kind and self.target_bytes > 0 and size <= self.target_bytes:
            self.t2[key] = size
            self.t2_bytes += size
            self.used_bytes += size
            self._rebalance()
        else:
            self.t1[key] = size
            self.t1_bytes += size
            self.used_bytes += size

        return evicted
