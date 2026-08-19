from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.items = OrderedDict()
        self.history = {}
        self.used_bytes = 0
        self.tick = 0

    def _observe(self, key):
        record = self.history.get(key)
        if record is None:
            self.history[key] = [1, self.tick]
        else:
            record[0] += 1
            record[1] = self.tick

        if self.tick % 128 == 0:
            stale = []
            for old_key, old_record in self.history.items():
                old_record[0] = max(1, (old_record[0] + 1) // 2)
                if (
                    old_record[0] == 1
                    and self.tick - old_record[1] > 512
                    and old_key not in self.items
                ):
                    stale.append(old_key)
            for old_key in stale:
                del self.history[old_key]

    def _score(self, key, size, last_touch):
        record = self.history.get(key)
        frequency = 1 if record is None else min(64, record[0])
        age = max(0, self.tick - last_touch)
        freshness = 1 + max(0, 32 - age)
        return ((frequency + 1) * freshness * 1024) // max(1, size)

    def _victim(self, exclude=None):
        selected = None
        selected_score = None
        for key, record in self.items.items():
            if key == exclude:
                continue
            score = self._score(key, record[0], record[1])
            if selected_score is None or score < selected_score:
                selected = key
                selected_score = score
        return selected

    def access(self, key: int, size: int, now: int) -> list[int]:
        del now
        self.tick += 1
        size = max(0, int(size))
        self._observe(key)

        if key in self.items:
            record = self.items.pop(key)
            self.used_bytes -= record[0]

            if size > self.capacity_bytes:
                return [key]

            record[0] = size
            record[1] = self.tick
            self.items[key] = record
            self.used_bytes += size

            evicted = []
            while self.used_bytes > self.capacity_bytes:
                victim = self._victim(exclude=key)
                if victim is None:
                    self.items.pop(key, None)
                    self.used_bytes -= size
                    evicted.append(key)
                    break
                victim_record = self.items.pop(victim)
                self.used_bytes -= victim_record[0]
                evicted.append(victim)
            return evicted

        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            victim = self._victim()
            if victim is None:
                break
            victim_record = self.items.pop(victim)
            self.used_bytes -= victim_record[0]
            evicted.append(victim)

        self.items[key] = [size, self.tick]
        self.used_bytes += size
        return evicted
