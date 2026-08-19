from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.used = 0

    def _remove_resident(self, key):
        value = self.recent.pop(key, None)
        if value is not None:
            self.used -= value[0]
            return value
        value = self.frequent.pop(key, None)
        if value is not None:
            self.used -= value[0]
            return value
        return None

    def _evict_one(self):
        if self.recent:
            key, value = self.recent.popitem(last=False)
        elif self.frequent:
            key, value = self.frequent.popitem(last=False)
        else:
            return None
        self.used -= value[0]
        return key

    def _make_room(self, incoming):
        evicted = []
        while self.used + incoming > self.capacity:
            key = self._evict_one()
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))

        resident = key in self.recent or key in self.frequent
        if resident:
            value = self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size)
            self.frequent[key] = (size, value[1] + 1)
            self.used += size
            return evicted

        if size <= 0 or size > self.capacity:
            return []

        evicted = self._make_room(size)
        self.recent[key] = (size, 1)
        self.used += size
        return evicted
