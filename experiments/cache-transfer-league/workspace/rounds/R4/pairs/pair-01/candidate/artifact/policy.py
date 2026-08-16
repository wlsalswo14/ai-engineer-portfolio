from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.entries = OrderedDict()
        self.used_bytes = 0
        self.tick = 0
        self.phase = 0
        self.window_hits = 0
        self.window_misses = 0
        self.window_hot_evictions = 0

    def _pick_victim(self):
        victim_key = None
        victim_rank = None
        for key, entry in self.entries.items():
            size, hits, last = entry
            if self.phase == 0:
                rank = (hits, last, -size)
            else:
                age = min(1024, self.tick - last)
                scaled_size = (size * 1024 + self.capacity_bytes - 1) // max(1, self.capacity_bytes)
                value = (hits + 1) * 1024 - scaled_size - age
                rank = (value, last, -size)
            if victim_rank is None or rank < victim_rank:
                victim_key = key
                victim_rank = rank
        return victim_key

    def _observe_window(self):
        if self.tick % 64 == 0:
            if (self.phase == 0 and self.window_hot_evictions > 0 and
                    self.window_misses >= self.window_hits):
                self.phase = 1
            self.window_hits = 0
            self.window_misses = 0
            self.window_hot_evictions = 0

    def access(self, key: int, size: int, now: int) -> list[int]:
        self.tick += 1

        if key in self.entries:
            entry = self.entries.pop(key)
            entry[1] = min(15, entry[1] + 1)
            entry[2] = self.tick
            self.entries[key] = entry
            self.window_hits += 1
            self._observe_window()
            return []

        self.window_misses += 1
        size = max(0, size)
        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            self._observe_window()
            return []

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            victim = self._pick_victim()
            if victim is None:
                break
            entry = self.entries.pop(victim)
            self.used_bytes -= entry[0]
            if entry[1] > 0:
                self.window_hot_evictions += 1
            evicted.append(victim)

        self.entries[key] = [size, 0, self.tick]
        self.used_bytes += size
        self._observe_window()
        return evicted
