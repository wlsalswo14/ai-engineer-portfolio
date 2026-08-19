from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        try:
            capacity = int(capacity_bytes)
        except Exception:
            capacity = 0
        self.capacity_bytes = max(0, capacity)
        self._target = 0
        self._t1 = OrderedDict()
        self._t2 = OrderedDict()
        self._b1 = OrderedDict()
        self._b2 = OrderedDict()
        self._resident_bytes = 0
        self._ghost_limit = 1024

    @staticmethod
    def _size(value):
        try:
            value = int(value)
        except Exception:
            value = 0
        return max(0, value)

    def _remove_resident(self, key):
        if key in self._t1:
            size = self._t1.pop(key)
            self._resident_bytes -= size
            return size, 1
        if key in self._t2:
            size = self._t2.pop(key)
            self._resident_bytes -= size
            return size, 2
        return None

    def _add_resident(self, table, key, size):
        self._b1.pop(key, None)
        self._b2.pop(key, None)
        table[key] = size
        self._resident_bytes += size

    def _remember_ghost(self, key, size, class_id):
        self._b1.pop(key, None)
        self._b2.pop(key, None)
        table = self._b1 if class_id == 1 else self._b2
        table[key] = size
        while len(self._b1) + len(self._b2) > self._ghost_limit:
            if self._b1 and (not self._b2 or len(self._b1) >= len(self._b2)):
                self._b1.popitem(last=False)
            elif self._b2:
                self._b2.popitem(last=False)

    def _adapt(self, from_b1):
        source = self._b1 if from_b1 else self._b2
        other = self._b2 if from_b1 else self._b1
        source_weight = sum(max(1, value) for value in source.values())
        other_weight = sum(max(1, value) for value in other.values())
        delta = max(1, other_weight // max(1, source_weight))
        if from_b1:
            self._target = min(self.capacity_bytes, self._target + delta)
        else:
            self._target = max(0, self._target - delta)

    def _choose_victim_table(self, from_b2):
        t1_bytes = sum(self._t1.values())
        if self._t1 and (t1_bytes > self._target or (from_b2 and t1_bytes == self._target)):
            return self._t1, 1
        if self._t2:
            return self._t2, 2
        if self._t1:
            return self._t1, 1
        return None, 0

    def _make_room(self, incoming_size, from_b2=False):
        evicted = []
        while self._resident_bytes + incoming_size > self.capacity_bytes:
            table, class_id = self._choose_victim_table(from_b2)
            if table is None:
                break
            key, size = table.popitem(last=False)
            self._resident_bytes -= size
            evicted.append(key)
            self._remember_ghost(key, size, class_id)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        size = self._size(size)
        resident = self._remove_resident(key)
        if resident is not None:
            old_size, old_class = resident
            if size > self.capacity_bytes:
                self._remember_ghost(key, old_size, old_class)
                return [key]
            evicted = self._make_room(size)
            self._add_resident(self._t2, key, size)
            return evicted

        if size > self.capacity_bytes:
            return []

        if key in self._b1:
            self._adapt(True)
            self._b1.pop(key, None)
            evicted = self._make_room(size, True)
            self._add_resident(self._t2, key, size)
            return evicted

        if key in self._b2:
            self._adapt(False)
            self._b2.pop(key, None)
            evicted = self._make_room(size, True)
            self._add_resident(self._t2, key, size)
            return evicted

        evicted = self._make_room(size, False)
        self._add_resident(self._t1, key, size)
        return evicted
