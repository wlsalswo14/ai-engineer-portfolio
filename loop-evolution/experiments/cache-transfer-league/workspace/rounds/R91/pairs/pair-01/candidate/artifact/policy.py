from collections import OrderedDict
import operator


class Policy:
    def __init__(self, capacity_bytes):
        try:
            capacity = operator.index(capacity_bytes)
        except (TypeError, ValueError):
            capacity = 0
        self.capacity_bytes = max(0, capacity)
        self._items = OrderedDict()
        self._used = 0

    def access(self, key, size, now):
        evicted = []
        if type(key) is not int:
            return evicted
        try:
            requested = operator.index(size)
        except (TypeError, ValueError):
            requested = 0

        previous = self._items.pop(key, None)
        if previous is not None:
            self._used -= previous

        if requested <= 0 or requested > self.capacity_bytes:
            if previous is not None:
                evicted.append(key)
            return evicted

        while self._used + requested > self.capacity_bytes:
            old_key, old_size = self._items.popitem(last=False)
            self._used -= old_size
            evicted.append(old_key)

        self._items[key] = requested
        self._used += requested
        return evicted
