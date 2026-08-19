from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.used = 0
        self.p = self.capacity // 2
        self.entries = {}
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.b1_bytes = 0
        self.b2_bytes = 0
        self.max_ghosts = 8192

    def _discard_ghost(self, ghosts, key, which):
        nonlocal_dummy = None
        if key in ghosts:
            size = ghosts.pop(key)
            if which == 1:
                self.b1_bytes -= size
            else:
                self.b2_bytes -= size

    def _remember(self, ghosts, key, size, which):
        self._discard_ghost(ghosts, key, which)
        ghosts[key] = size
        if which == 1:
            self.b1_bytes += size
        else:
            self.b2_bytes += size
        while len(ghosts) > self.max_ghosts:
            old_key, old_size = ghosts.popitem(last=False)
            if which == 1:
                self.b1_bytes -= old_size
            else:
                self.b2_bytes -= old_size

    def _remove_resident(self, key, remember=True):
        entry = self.entries.pop(key, None)
        if entry is None:
            return None
        size, segment = entry
        self.used -= size
        if segment == 1:
            self.t1.pop(key, None)
            if remember:
                self._remember(self.b1, key, size, 1)
        else:
            self.t2.pop(key, None)
            if remember:
                self._remember(self.b2, key, size, 2)
        return key

    def _make_room(self, amount, incoming_b2, evicted):
        while self.used + amount > self.capacity and self.entries:
            if self.t1 and (self.t1_bytes() > self.p or (incoming_b2 and self.t1_bytes() == self.p)):
                key = next(iter(self.t1))
            elif self.t2:
                key = next(iter(self.t2))
            else:
                key = next(iter(self.t1))
            removed = self._remove_resident(key, True)
            if removed is not None:
                evicted.append(removed)

    def t1_bytes(self):
        return sum(self.entries[key][0] for key in self.t1)

    def _insert(self, key, size, segment):
        self.entries[key] = (size, segment)
        if segment == 1:
            self.t1[key] = None
        else:
            self.t2[key] = None
        self.used += size

    def access(self, key: int, size: int, now: int) -> list[int]:
        size = max(0, int(size))
        evicted = []

        if self.capacity == 0 or size > self.capacity:
            if key in self.entries:
                self._remove_resident(key, False)
                evicted.append(key)
            for resident in list(self.entries):
                self._remove_resident(resident, False)
                if resident not in evicted:
                    evicted.append(resident)
            self.b1.clear()
            self.b2.clear()
            self.b1_bytes = 0
            self.b2_bytes = 0
            return evicted

        entry = self.entries.get(key)
        if entry is not None:
            old_size, segment = entry
            self.used += size - old_size
            self.entries[key] = (size, 2)
            if segment == 1:
                self.t1.pop(key, None)
            else:
                self.t2.pop(key, None)
            self.t2[key] = None
            self._make_room(0, False, evicted)
            return evicted

        in_b1 = key in self.b1
        in_b2 = key in self.b2
        if in_b1:
            old = self.b1.pop(key)
            self.b1_bytes -= old
            step = max(size, self.b2_bytes // max(1, self.b1_bytes))
            self.p = min(self.capacity, self.p + step)
        elif in_b2:
            old = self.b2.pop(key)
            self.b2_bytes -= old
            step = max(size, self.b1_bytes // max(1, self.b2_bytes))
            self.p = max(0, self.p - step)

        self._make_room(size, in_b2, evicted)
        self._insert(key, size, 2 if (in_b1 or in_b2) else 1)
        return evicted
