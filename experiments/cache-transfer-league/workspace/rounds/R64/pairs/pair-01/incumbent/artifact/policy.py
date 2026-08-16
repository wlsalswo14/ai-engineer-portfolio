from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        try:
            capacity_bytes = int(capacity_bytes)
        except (TypeError, ValueError):
            capacity_bytes = 0
        self.capacity_bytes = max(0, capacity_bytes)
        self._target = self.capacity_bytes // 2
        self._resident = {}
        self._where = {}
        self._t1 = OrderedDict()
        self._t2 = OrderedDict()
        self._b1 = OrderedDict()
        self._b2 = OrderedDict()
        self._bytes = 0
        self._t1_bytes = 0
        self._t2_bytes = 0
        self._max_entries = 4096
        self._max_ghost = 4096

    def _size(self, size):
        try:
            size = int(size)
        except (TypeError, ValueError):
            size = 0
        return max(0, size)

    def _remember(self, table, key, size):
        self._b1.pop(key, None)
        self._b2.pop(key, None)
        table[key] = max(0, size)
        table.move_to_end(key)
        while len(table) > self._max_ghost:
            table.popitem(last=False)

    def _remove_resident(self, key, remember=True):
        if key not in self._resident:
            return None
        size = self._resident.pop(key)
        region = self._where.pop(key)
        if region == 1:
            self._t1.pop(key, None)
            self._t1_bytes -= size
            if remember:
                self._remember(self._b1, key, size)
        else:
            self._t2.pop(key, None)
            self._t2_bytes -= size
            if remember:
                self._remember(self._b2, key, size)
        self._bytes -= size
        if self._bytes < 0:
            self._bytes = 0
        if self._t1_bytes < 0:
            self._t1_bytes = 0
        if self._t2_bytes < 0:
            self._t2_bytes = 0
        return size

    def _oldest_other(self, table, protected):
        for key in table:
            if key != protected:
                return key
        return None

    def _trim(self, protected=None):
        evicted = []
        seen = set()
        while self._resident and (
            self._bytes > self.capacity_bytes
            or len(self._resident) > self._max_entries
        ):
            key = None
            if self._t1 and (self._t1_bytes > self._target or not self._t2):
                key = self._oldest_other(self._t1, protected)
                if key is None:
                    key = self._oldest_other(self._t2, protected)
            else:
                key = self._oldest_other(self._t2, protected)
                if key is None:
                    key = self._oldest_other(self._t1, protected)
            if key is None:
                break
            self._remove_resident(key, remember=True)
            if key not in seen:
                seen.add(key)
                evicted.append(key)
        return evicted

    def _adjust_target(self, increase, evidence):
        if self.capacity_bytes <= 0:
            self._target = 0
            return
        evidence = max(0, evidence)
        delta = max(1, min(self.capacity_bytes, evidence))
        if increase:
            self._target = min(self.capacity_bytes, self._target + delta)
        else:
            self._target = max(0, self._target - delta)

    def access(self, key: int, size: int, now: int) -> list[int]:
        size = self._size(size)
        if key in self._resident:
            old_size = self._resident[key]
            if size > self.capacity_bytes:
                self._remove_resident(key, remember=True)
                return [key]
            region = self._where[key]
            self._resident[key] = size
            self._bytes += size - old_size
            if region == 1:
                self._t1.pop(key, None)
                self._t1_bytes += size - old_size
                self._t2[key] = size
                self._t2_bytes += size
                self._where[key] = 2
            else:
                self._t2[key] = size
                self._t2.move_to_end(key)
                self._t2_bytes += size - old_size
            self._b1.pop(key, None)
            self._b2.pop(key, None)
            return self._trim(protected=key)

        if size > self.capacity_bytes:
            return []

        ghost_size = None
        if key in self._b1:
            ghost_size = self._b1.pop(key)
            self._adjust_target(True, max(size, ghost_size))
        elif key in self._b2:
            ghost_size = self._b2.pop(key)
            self._adjust_target(False, max(size, ghost_size))

        if ghost_size is None:
            self._t1[key] = size
            self._where[key] = 1
            self._t1_bytes += size
        else:
            self._t2[key] = size
            self._where[key] = 2
            self._t2_bytes += size
        self._resident[key] = size
        self._bytes += size
        return self._trim(protected=key)
