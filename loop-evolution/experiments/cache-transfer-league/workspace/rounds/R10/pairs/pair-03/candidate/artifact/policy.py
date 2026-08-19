from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.entries = {}
        self.history = OrderedDict()
        self.used_bytes = 0
        self.history_limit = 2048
        self.history_window = 4096
        self.minimum_ttl = 16
        self.maximum_ttl = 4096

    def _ttl(self, entry):
        gap = max(1, entry[3])
        return max(self.minimum_ttl, min(self.maximum_ttl, gap * 4 + 16))

    def _remember(self, key, now, reuse):
        self.history.pop(key, None)
        self.history[key] = (now, max(0, reuse))
        while len(self.history) > self.history_limit:
            self.history.popitem(last=False)

    def _expire_stale(self, now, keep):
        evicted = []
        for cached_key, entry in list(self.entries.items()):
            if cached_key == keep:
                continue
            age = max(0, now - entry[1])
            if age > self._ttl(entry):
                del self.entries[cached_key]
                self.used_bytes -= entry[0]
                self._remember(cached_key, now, 0)
                evicted.append(cached_key)
        return evicted

    def _victim_order(self, now):
        return sorted(
            self.entries,
            key=lambda cached_key: (
                self.entries[cached_key][2],
                self.entries[cached_key][1],
                cached_key,
            ),
        )

    def access(self, key: int, size: int, now: int) -> list[int]:
        now = int(now)
        size = max(0, int(size))
        evicted = self._expire_stale(now, key)

        entry = self.entries.get(key)
        if entry is not None:
            age = max(0, now - entry[1])
            if age > 0:
                if entry[3] <= 0:
                    entry[3] = age
                else:
                    entry[3] = (entry[3] * 3 + age + 1) // 4
            entry[1] = now
            entry[2] += 1
            return evicted

        prior = self.history.pop(key, None)
        if prior is None or now - prior[0] > self.history_window:
            reuse = 0
        else:
            reuse = min(255, prior[1] + 1)

        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            self._remember(key, now, reuse)
            return evicted

        while self.used_bytes + size > self.capacity_bytes:
            order = self._victim_order(now)
            if not order:
                break
            victim = order[0]
            victim_entry = self.entries.pop(victim)
            self.used_bytes -= victim_entry[0]
            self._remember(victim, now, victim_entry[2])
            evicted.append(victim)

        self.entries[key] = [size, now, reuse, 0]
        self.used_bytes += size
        return evicted
