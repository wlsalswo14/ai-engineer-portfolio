from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.cold = OrderedDict()
        self.hot = OrderedDict()
        self.cold_bytes = 0
        self.hot_bytes = 0
        self.hot_target = self.capacity_bytes // 2
        self.ghost_limit = 4096
        self.ghost_cold = OrderedDict()
        self.ghost_hot = OrderedDict()
        self.width = 2048
        self.mask = 0xffffffffffffffff
        self.seeds = (0x9e3779b97f4a7c15, 0xbf58476d1ce4e5b9, 0x94d049bb133111eb, 0xd6e8feb86659fd93)
        self.sketch = [[0] * self.width for _ in self.seeds]
        self.ticks = 0

    def _mix(self, value, seed):
        x = ((int(value) & self.mask) ^ seed) & self.mask
        x = (((x ^ (x >> 30)) * 0xbf58476d1ce4e5b9) & self.mask)
        x = (((x ^ (x >> 27)) * 0x94d049bb133111eb) & self.mask)
        return (x ^ (x >> 31)) & self.mask

    def _touch_frequency(self, key):
        self.ticks += 1
        for row, seed in zip(self.sketch, self.seeds):
            index = self._mix(key, seed) % self.width
            if row[index] < 65535:
                row[index] += 1
        if (self.ticks & 4095) == 0:
            for row in self.sketch:
                for index in range(self.width):
                    row[index] >>= 1

    def _frequency(self, key):
        return min(row[self._mix(key, seed) % self.width] for row, seed in zip(self.sketch, self.seeds))

    def _drop_ghost(self, key):
        self.ghost_cold.pop(key, None)
        self.ghost_hot.pop(key, None)

    def _remember_ghost(self, ghost, other, key, size):
        other.pop(key, None)
        ghost.pop(key, None)
        ghost[key] = size
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _remove_resident(self, key):
        if key in self.cold:
            size = self.cold.pop(key)
            self.cold_bytes -= size
            return size, False
        if key in self.hot:
            size = self.hot.pop(key)
            self.hot_bytes -= size
            return size, True
        return None, False

    def _add_cold(self, key, size):
        self.cold[key] = size
        self.cold_bytes += size

    def _add_hot(self, key, size):
        self.hot[key] = size
        self.hot_bytes += size

    def _rebalance_hot(self):
        while len(self.hot) > 1 and self.hot_bytes > self.hot_target:
            key, size = self.hot.popitem(last=False)
            self.hot_bytes -= size
            self._add_cold(key, size)

    def _choose_cold_victim(self):
        if not self.cold:
            return None
        best_key = None
        best_size = 0
        best_frequency = 0
        for position, (key, size) in enumerate(self.cold.items()):
            if position >= 32:
                break
            frequency = self._frequency(key)
            if best_key is None:
                best_key = key
                best_size = size
                best_frequency = frequency
                continue
            left = (frequency + 1) * best_size
            right = (best_frequency + 1) * size
            if left < right:
                best_key = key
                best_size = size
                best_frequency = frequency
        return best_key

    def _make_room(self, size):
        evicted = []
        while self.cold_bytes + self.hot_bytes + size > self.capacity_bytes:
            key = self._choose_cold_victim()
            if key is not None:
                victim_size = self.cold.pop(key)
                self.cold_bytes -= victim_size
                self._remember_ghost(self.ghost_cold, self.ghost_hot, key, victim_size)
                evicted.append(key)
                continue
            if not self.hot:
                break
            key, victim_size = self.hot.popitem(last=False)
            self.hot_bytes -= victim_size
            self._remember_ghost(self.ghost_hot, self.ghost_cold, key, victim_size)
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        requested = int(size)

        if requested <= 0:
            if key in self.cold:
                self.cold.move_to_end(key)
            elif key in self.hot:
                self.hot.move_to_end(key)
            return []

        old_size, was_hot = self._remove_resident(key)

        if requested > self.capacity_bytes:
            if old_size is not None:
                if was_hot:
                    self._remember_ghost(self.ghost_hot, self.ghost_cold, key, old_size)
                else:
                    self._remember_ghost(self.ghost_cold, self.ghost_hot, key, old_size)
                return [key]
            return []

        self._touch_frequency(key)

        if old_size is not None:
            evicted = self._make_room(requested)
            self._add_hot(key, requested)
            self._rebalance_hot()
            return evicted

        cold_hit = key in self.ghost_cold
        hot_hit = key in self.ghost_hot
        if cold_hit or hot_hit:
            step = max(1, self.capacity_bytes // 16)
            if cold_hit:
                self.hot_target = max(0, self.hot_target - step)
            else:
                self.hot_target = min(self.capacity_bytes, self.hot_target + step)
        self._drop_ghost(key)

        evicted = self._make_room(requested)
        if cold_hit or hot_hit:
            self._add_hot(key, requested)
            self._rebalance_hot()
        else:
            self._add_cold(key, requested)
        return evicted
