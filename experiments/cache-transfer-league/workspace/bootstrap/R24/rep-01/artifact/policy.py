from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = capacity_bytes
        self.cache = OrderedDict()
        self.used_bytes = 0

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.cache:
            stored_size = self.cache.pop(key)
            self.cache[key] = stored_size
            return []

        if size > self.capacity_bytes:
            return []

        evicted = []
        while self.used_bytes + size > self.capacity_bytes and self.cache:
            old_key, old_size = self.cache.popitem(last=False)
            self.used_bytes -= old_size
            evicted.append(old_key)

        self.cache[key] = size
        self.used_bytes += size
        return evicted
