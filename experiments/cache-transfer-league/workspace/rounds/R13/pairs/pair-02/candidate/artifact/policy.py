from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self._items = {}
        self._probation = OrderedDict()
        self._protected = OrderedDict()
        self._used = 0
        self._protected_bytes = 0

    def _protected_limit(self):
        if self.capacity_bytes <= 1:
            return self.capacity_bytes
        return max(1, (self.capacity_bytes * 2) // 3)

    def _remove(self, key):
        size, _, protected = self._items.pop(key)
        self._probation.pop(key, None)
        self._protected.pop(key, None)
        self._used -= size
        if protected:
            self._protected_bytes -= size

    def _rebalance(self):
        limit = self._protected_limit()
        while self._protected and self._protected_bytes > limit:
            key, _ = self._protected.popitem(last=False)
            entry = self._items.get(key)
            if entry is None or not entry[2]:
                continue
            entry[2] = False
            self._protected_bytes -= entry[0]
            self._probation[key] = None

    def _touch(self, key):
        entry = self._items[key]
        entry[1] = min(entry[1] + 1, 15)
        if entry[2]:
            self._protected.move_to_end(key)
        elif entry[1] >= 2:
            self._probation.pop(key, None)
            entry[2] = True
            self._protected[key] = None
            self._protected_bytes += entry[0]
            self._rebalance()
        else:
            self._probation.move_to_end(key)

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self._items:
            self._touch(key)
            return []

        size = max(0, size)
        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            return []

        evicted = []
        while self._used + size > self.capacity_bytes:
            if self._probation:
                victim, _ = self._probation.popitem(last=False)
            elif self._protected:
                victim, _ = self._protected.popitem(last=False)
            else:
                break
            self._remove(victim)
            evicted.append(victim)

        if self._used + size > self.capacity_bytes:
            return evicted

        self._items[key] = [size, 1, False]
        self._probation[key] = None
        self._used += size
        return evicted
