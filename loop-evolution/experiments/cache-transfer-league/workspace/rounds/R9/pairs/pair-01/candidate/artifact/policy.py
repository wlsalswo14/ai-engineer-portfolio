class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self._items = {}
        self._used = 0
        self._tick = 0
        self._credit_cap = 32
        self._scale = 1000000

    def _score(self, record):
        size, credit, last, _ = record
        age = max(0, self._tick - last)
        return credit * self._scale // ((age + 1) * max(1, size))

    def _victim(self):
        selected_key = None
        selected_rank = None
        for candidate, record in self._items.items():
            rank = (self._score(record), record[2], record[3], candidate)
            if selected_rank is None or rank < selected_rank:
                selected_key = candidate
                selected_rank = rank
        return selected_key

    def access(self, key: int, size: int, now: int) -> list[int]:
        self._tick += 1

        record = self._items.get(key)
        if record is not None:
            stored_size, credit, _, born = record
            self._items[key] = (
                stored_size,
                min(self._credit_cap, credit + 1),
                self._tick,
                born,
            )
            return []

        item_size = max(0, int(size))
        if self.capacity_bytes == 0 or item_size > self.capacity_bytes:
            return []

        evicted = []
        while self._used + item_size > self.capacity_bytes and self._items:
            victim = self._victim()
            victim_record = self._items.pop(victim)
            self._used -= victim_record[0]
            evicted.append(victim)

        self._items[key] = (item_size, 1, self._tick, self._tick)
        self._used += item_size
        return evicted
