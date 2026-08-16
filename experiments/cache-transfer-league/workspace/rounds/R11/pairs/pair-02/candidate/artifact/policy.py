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
        self.ghost_limit_bytes = max(64, min(1 << 20, self.capacity_bytes * 2 + 64))
        self.ghost_limit_entries = 4096

    def _remove_ghost(self, key):
        if key in self.b1:
            size = self.b1.pop(key)
            self.b1_bytes -= size
        if key in self.b2:
            size = self.b2.pop(key)
            self.b2_bytes -= size

    def _remember(self, target, key, size):
        self._remove_ghost(key)
        target[key] = size
        if target is self.b1:
            self.b1_bytes += size
        else:
            self.b2_bytes += size
        while (self.b1_bytes + self.b2_bytes > self.ghost_limit_bytes or
               len(self.b1) + len(self.b2) > self.ghost_limit_entries):
            if self.b1:
                old_key, old_size = self.b1.popitem(last=False)
                self.b1_bytes -= old_size
            elif self.b2:
                old_key, old_size = self.b2.popitem(last=False)
                self.b2_bytes -= old_size
            else:
                break

    def _replace(self, incoming, evicted, prefer_t2):
        while self.used_bytes + incoming > self.capacity_bytes:
            if not self.t1 and not self.t2:
                break
            choose_t1 = bool(self.t1) and (
                not self.t2 or
                self.t1_bytes > self.target_t1_bytes or
                (prefer_t2 and self.t1_bytes == self.target_t1_bytes)
            )
            if choose_t1:
                key, size = self.t1.popitem(last=False)
                self.t1_bytes -= size
                self._remember(self.b1, key, size)
            elif self.t2:
                key, size = self.t2.popitem(last=False)
                self.t2_bytes -= size
                self._remember(self.b2, key, size)
            else:
                key, size = self.t1.popitem(last=False)
                self.t1_bytes -= size
                self._remember(self.b1, key, size)
            self.used_bytes -= size
            evicted.append(key)

    def _increase_target(self, incoming):
        ratio = max(1, self.b2_bytes // max(1, self.b1_bytes))
        step = max(1, min(self.capacity_bytes, ratio * max(1, incoming)))
        self.target_t1_bytes = min(self.capacity_bytes,
                                   self.target_t1_bytes + step)

    def _decrease_target(self, incoming):
        ratio = max(1, self.b1_bytes // max(1, self.b2_bytes))
        step = max(1, min(self.capacity_bytes, ratio * max(1, incoming)))
        self.target_t1_bytes = max(0, self.target_t1_bytes - step)

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

        incoming = max(0, int(size))
        if self.capacity_bytes == 0 or incoming > self.capacity_bytes:
            return []

        in_b1 = key in self.b1
        in_b2 = key in self.b2
        if in_b1:
            self._increase_target(incoming)
        elif in_b2:
            self._decrease_target(incoming)
        self._remove_ghost(key)

        evicted = []
        self._replace(incoming, evicted, in_b2)

        if in_b1 or in_b2:
            self.t2[key] = incoming
            self.t2_bytes += incoming
        else:
            self.t1[key] = incoming
            self.t1_bytes += incoming
        self.used_bytes += incoming
        return evicted
