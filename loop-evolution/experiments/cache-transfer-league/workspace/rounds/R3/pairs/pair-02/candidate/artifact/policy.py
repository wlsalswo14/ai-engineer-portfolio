from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        if capacity_bytes < 0:
            raise ValueError("capacity_bytes must be non-negative")
        self.capacity_bytes = capacity_bytes
        self._items = OrderedDict()
        self._used_bytes = 0

    def access(self, key, size, now):
        if size < 0:
            raise ValueError("size must be non-negative")

        evicted = []
        old_size = self._items.pop(key, None)
        if old_size is not None:
            self._used_bytes -= old_size

        while self._items and self._used_bytes + size > self.capacity_bytes:
            old_key, old_item_size = self._items.popitem(last=False)
            self._used_bytes -= old_item_size
            evicted.append(old_key)

        if size <= self.capacity_bytes:
            self._items[key] = size
            self._used_bytes += size

        return evicted
