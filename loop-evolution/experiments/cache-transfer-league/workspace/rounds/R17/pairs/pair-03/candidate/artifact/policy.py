class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self._cache = {}
        self._used = 0
        self._calls = 0
        self._mask = (1 << 64) - 1
        self._salts = (0x9E3779B97F4A7C15, 0xD1B54A32D192ED03, 0x94D049BB133111EB, 0xBF58476D1CE4E5B9)
        self._table = [[0] * 2048 for _ in self._salts]

    def _mix(self, key, salt):
        x = (key & self._mask) ^ salt
        x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & self._mask
        x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & self._mask
        return (x ^ (x >> 31)) & self._mask

    def _index(self, key, salt):
        return self._mix(key, salt) & 2047

    def _fingerprint(self, key):
        return self._mix(key, 0x243F6A8885A308D3)

    def _touch(self, key):
        for row, salt in zip(self._table, self._salts):
            index = self._index(key, salt)
            if row[index] < 255:
                row[index] += 1
        self._calls += 1
        if self._calls % 256 == 0:
            for row in self._table:
                for index in range(len(row)):
                    row[index] >>= 1

    def _estimate(self, key):
        estimate = 255
        for row, salt in zip(self._table, self._salts):
            value = row[self._index(key, salt)]
            if value < estimate:
                estimate = value
        return estimate

    def _lower(self, a_key, a_size, a_freq, b_key, b_size, b_freq):
        left = a_freq * b_size
        right = b_freq * a_size
        if left != right:
            return left < right
        a_hash = self._fingerprint(a_key)
        b_hash = self._fingerprint(b_key)
        if a_hash != b_hash:
            return a_hash < b_hash
        return a_key < b_key

    def _lowest(self, keys):
        best = None
        for key in keys:
            size = self._cache[key]
            frequency = self._estimate(key)
            if best is None or self._lower(key, size, frequency, best[0], best[1], best[2]):
                best = (key, size, frequency)
        return best

    def access(self, key: int, size: int, now: int) -> list[int]:
        self._touch(key)
        if key in self._cache:
            return []
        if size <= 0 or size > self.capacity_bytes:
            return []

        candidate_frequency = self._estimate(key)
        remaining = list(self._cache)
        selected = []
        needed = self._used + size - self.capacity_bytes

        while needed > 0:
            victim = self._lowest(remaining)
            if victim is None:
                return []
            if self._lower(key, size, candidate_frequency, victim[0], victim[1], victim[2]):
                return []
            selected.append(victim)
            remaining.remove(victim[0])
            needed -= victim[1]

        evicted = []
        for old_key, old_size, _ in selected:
            del self._cache[old_key]
            self._used -= old_size
            evicted.append(old_key)

        self._cache[key] = size
        self._used += size
        return evicted
