from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        try:
            capacity_bytes = int(capacity_bytes)
        except Exception:
            capacity_bytes = 0
        self.capacity = max(0, capacity_bytes)
        self.resident = {}
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.used = 0
        self.t1_bytes = 0
        self.t2_bytes = 0
        self.protected_target = self.capacity // 2
        self.sequence = 0
        self.operations = 0
        self.entry_limit = 4096
        self.ghost_limit = 4096

    @staticmethod
    def _size(value):
        try:
            value = int(value)
        except Exception:
            value = 0
        return max(0, value)

    def _remember_ghost(self, key, size, segment):
        target = self.b1 if segment == 1 else self.b2
        other = self.b2 if segment == 1 else self.b1
        other.pop(key, None)
        target[key] = (size, self.sequence)
        target.move_to_end(key)
        while len(target) > self.ghost_limit:
            target.popitem(last=False)

    def _remove(self, key, remember=True):
        entry = self.resident.pop(key, None)
        if entry is None:
            return None
        size, _, segment, _ = entry
        if segment == 1:
            self.t1.pop(key, None)
            self.t1_bytes -= size
        else:
            self.t2.pop(key, None)
            self.t2_bytes -= size
        self.used -= size
        if remember:
            self._remember_ghost(key, size, segment)
        return key

    def _oldest_other(self, queue, avoid):
        for key in queue:
            if key != avoid:
                return key
        return None

    def _protected_victim(self, avoid):
        candidates = []
        for key, entry in list(self.t2.items())[:64]:
            if key != avoid:
                candidates.append((entry[1], -entry[3], key))
        if not candidates:
            return None
        candidates.sort()
        return candidates[0][2]

    def _victim(self, avoid=None):
        recent_target = self.capacity - self.protected_target
        if self.t1 and (self.t1_bytes > recent_target or not self.t2):
            key = self._oldest_other(self.t1, avoid)
            if key is not None:
                return key
        key = self._protected_victim(avoid)
        if key is not None:
            return key
        key = self._oldest_other(self.t1, avoid)
        if key is not None:
            return key
        return self._oldest_other(self.t2, avoid)

    def _enforce(self, evicted, avoid=None):
        while self.used > self.capacity or len(self.resident) > self.entry_limit:
            victim = self._victim(avoid)
            if victim is None:
                break
            removed = self._remove(victim, remember=True)
            if removed is not None:
                evicted.append(removed)

    def _age_frequencies(self):
        for entry in self.resident.values():
            entry[1] = max(1, (entry[1] + 1) // 2)

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = self._size(size)
        self.sequence += 1
        self.operations += 1
        if self.operations % 1024 == 0:
            self._age_frequencies()

        evicted = []
        entry = self.resident.get(key)

        if entry is not None:
            if size > self.capacity:
                removed = self._remove(key, remember=True)
                return [removed] if removed is not None else []

            old_size = entry[0]
            segment = entry[2]
            if size != old_size:
                entry[0] = size
                delta = size - old_size
                self.used += delta
                if segment == 1:
                    self.t1_bytes += delta
                else:
                    self.t2_bytes += delta

            entry[1] = min(entry[1] + 1, 1000000000)
            entry[3] = self.sequence

            if segment == 1:
                self.t1.pop(key, None)
                self.t1_bytes -= size
                entry[2] = 2
                self.t2[key] = entry
                self.t2_bytes += size
            else:
                self.t2.move_to_end(key)

            self._enforce(evicted, avoid=key)
            return evicted

        in_b1 = key in self.b1
        in_b2 = key in self.b2
        if in_b1 or in_b2:
            if in_b1:
                self.b1.pop(key, None)
                step = max(1, min(self.capacity, size or 1) // 4)
                self.protected_target = min(self.capacity, self.protected_target + step)
                segment = 2
            else:
                self.b2.pop(key, None)
                step = max(1, min(self.capacity, size or 1) // 4)
                self.protected_target = max(0, self.protected_target - step)
                segment = 2
        else:
            segment = 1

        self.b1.pop(key, None)
        self.b2.pop(key, None)

        if self.capacity == 0 or size > self.capacity:
            return evicted

        entry = [size, 1, segment, self.sequence]
        self.resident[key] = entry
        if segment == 1:
            self.t1[key] = entry
            self.t1_bytes += size
        else:
            self.t2[key] = entry
            self.t2_bytes += size
        self.used += size

        self._enforce(evicted, avoid=key)
        return evicted
