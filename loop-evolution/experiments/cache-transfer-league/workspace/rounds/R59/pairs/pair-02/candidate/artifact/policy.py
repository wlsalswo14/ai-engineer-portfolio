class Policy:
    def __init__(self, capacity_bytes):
        self.capacity = max(0, int(capacity_bytes))
        self._items = {}
        self._used = 0

    def _victim(self, exclude):
        chosen = None
        for key, item in self._items.items():
            if key == exclude:
                continue
            if chosen is None:
                chosen = key
                continue
            size, hits = item
            chosen_size, chosen_hits = self._items[chosen]
            left = hits * chosen_size
            right = chosen_hits * size
            if left < right or (left == right and (size > chosen_size or (size == chosen_size and key < chosen))):
                chosen = key
        return chosen

    def _remove(self, key, evicted):
        item = self._items.pop(key)
        self._used -= item[0]
        evicted.append(key)

    def access(self, key, size, now):
        if type(key) is not int:
            return []
        try:
            size = int(size)
        except (TypeError, ValueError, OverflowError):
            return []

        evicted = []
        existing = key in self._items

        if size <= 0:
            if existing:
                self._remove(key, evicted)
            return evicted

        if size > self.capacity:
            if existing:
                self._remove(key, evicted)
            return evicted

        if existing:
            item = self._items[key]
            self._used += size - item[0]
            item[0] = size
            item[1] += 1
        else:
            self._items[key] = [size, 1]
            self._used += size

        while self._used > self.capacity:
            victim = self._victim(key)
            if victim is None:
                self._remove(key, evicted)
                break
            self._remove(victim, evicted)

        if self._used > self.capacity and key in self._items:
            self._remove(key, evicted)
        return evicted
