class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self._items = {}
        self._bytes = 0
        self._tick = 0

    def _decay(self):
        if self._tick % 256:
            return
        cutoff = self._tick - 512
        for entry in self._items.values():
            if entry[1] > 1:
                entry[1] = max(1, entry[1] // 2)
            if entry[3] and entry[2] < cutoff:
                entry[3] = False

    def _victim(self):
        victim_key = None
        victim_entry = None
        victim_score = 0
        for candidate, entry in self._items.items():
            if entry[0] <= 0:
                continue
            age = self._tick - entry[2]
            score = entry[1] * 1024 + max(0, 256 - age)
            if entry[3]:
                score += 2048
            if victim_entry is None:
                victim_key = candidate
                victim_entry = entry
                victim_score = score
                continue
            left = score * victim_entry[0]
            right = victim_score * entry[0]
            older = entry[2] < victim_entry[2]
            same_time = entry[2] == victim_entry[2]
            if left < right or (left == right and (older or (same_time and candidate < victim_key))):
                victim_key = candidate
                victim_entry = entry
                victim_score = score
        return victim_key

    def access(self, key: int, size: int, now: int) -> list[int]:
        self._tick += 1
        self._decay()
        requested = max(0, int(size))

        if key in self._items:
            entry = self._items[key]
            entry[1] += 1
            entry[2] = self._tick
            entry[3] = True
            return []

        if self.capacity_bytes <= 0 or requested > self.capacity_bytes:
            return []

        evicted = []
        needed = self._bytes + requested - self.capacity_bytes
        while needed > 0:
            victim_key = self._victim()
            if victim_key is None:
                break
            victim_entry = self._items.pop(victim_key)
            self._bytes -= victim_entry[0]
            needed -= victim_entry[0]
            evicted.append(victim_key)

        self._items[key] = [requested, 1, self._tick, False]
        self._bytes += requested
        return evicted
