from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.ghost_limit = 4096
        self.frequent_target = self.capacity_bytes // 2
        self.frequent_bytes = 0
        self.used_bytes = 0
        self.sketch_width = 2048
        self.sketch = [[0] * self.sketch_width for _ in range(4)]
        self.events = 0
        self.mask = (1 << 64) - 1

    def _slot(self, key, salt):
        x = (int(key) + salt) & self.mask
        x ^= x >> 30
        x = (x * 0xbf58476d1ce4e5b9) & self.mask
        x ^= x >> 27
        x = (x * 0x94d049bb133111eb) & self.mask
        x ^= x >> 31
        return x % self.sketch_width

    def _touch(self, key):
        salts = (0x9e3779b97f4a7c15, 0xc2b2ae3d27d4eb4f, 0x165667b19e3779f9, 0xd6e8feb86659fd93)
        for row, salt in zip(self.sketch, salts):
            slot = self._slot(key, salt)
            if row[slot] < 255:
                row[slot] += 1
        self.events += 1
        if self.events >= 4096:
            self.events = 0
            for row in self.sketch:
                for index, value in enumerate(row):
                    row[index] = value >> 1

    def _frequency(self, key):
        salts = (0x9e3779b97f4a7c15, 0xc2b2ae3d27d4eb4f, 0x165667b19e3779f9, 0xd6e8feb86659fd93)
        return min(row[self._slot(key, salt)] for row, salt in zip(self.sketch, salts))

    def _remember(self, ghost, key):
        self.ghost_recent.pop(key, None)
        self.ghost_frequent.pop(key, None)
        ghost[key] = None
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _forget_ghost(self, key):
        self.ghost_recent.pop(key, None)
        self.ghost_frequent.pop(key, None)

    def _rebalance(self):
        while self.frequent and self.frequent_bytes > self.frequent_target:
            old_key, old_size = self.frequent.popitem(last=False)
            self.frequent_bytes -= old_size
            self.recent[old_key] = old_size

    def _remove(self, key):
        if key in self.recent:
            size = self.recent.pop(key)
            self._remember(self.ghost_recent, key)
        elif key in self.frequent:
            size = self.frequent.pop(key)
            self.frequent_bytes -= size
            self._remember(self.ghost_frequent, key)
        else:
            return None
        self.used_bytes -= size
        return key

    def access(self, key: int, size: int, now: int) -> list[int]:
        self._touch(key)

        if key in self.frequent:
            stored_size = self.frequent.pop(key)
            self.frequent[key] = stored_size
            return []

        if key in self.recent:
            stored_size = self.recent.pop(key)
            self.frequent[key] = stored_size
            self.frequent_bytes += stored_size
            self._rebalance()
            return []

        if size <= 0 or size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        step = max(1, self.capacity_bytes // 32)
        if key in self.ghost_recent:
            self.frequent_target = min(self.capacity_bytes, self.frequent_target + max(step, min(size, self.capacity_bytes)))
        elif key in self.ghost_frequent:
            self.frequent_target = max(0, self.frequent_target - max(step, min(size, self.capacity_bytes)))
        self._rebalance()

        incoming_frequency = self._frequency(key)
        required = self.used_bytes + size - self.capacity_bytes
        planned = []
        planned_bytes = 0
        if required > 0:
            for queue in (self.recent, self.frequent):
                for candidate, candidate_size in queue.items():
                    if self._frequency(candidate) > incoming_frequency:
                        return []
                    planned.append(candidate)
                    planned_bytes += candidate_size
                    if planned_bytes >= required:
                        break
                if planned_bytes >= required:
                    break

        evicted = []
        for candidate in planned:
            removed = self._remove(candidate)
            if removed is not None:
                evicted.append(removed)

        self._forget_ghost(key)
        self.recent[key] = size
        self.used_bytes += size
        return evicted
