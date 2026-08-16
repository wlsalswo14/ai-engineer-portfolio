from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        try:
            capacity_bytes = int(capacity_bytes)
        except (TypeError, ValueError, OverflowError):
            capacity_bytes = 0
        self.capacity_bytes = max(0, capacity_bytes)
        self._items = {}
        self._probation = OrderedDict()
        self._protected = OrderedDict()
        self._protected_bytes = 0
        self._bytes = 0
        self._tick = 0
        self._pressure = 35
        self._history = {}

    def _size(self, value):
        try:
            value = int(value)
        except (TypeError, ValueError, OverflowError):
            return 0
        return value if value > 0 else 0

    def _age(self):
        if self._tick % 1024 != 0:
            return
        for entry in self._items.values():
            entry[2] = max(1, entry[2] // 2)
        for key, record in list(self._history.items()):
            count, last = record
            count //= 2
            if count == 0 and key not in self._items:
                del self._history[key]
            else:
                self._history[key] = (max(1, count), last)

    def _remember(self, key):
        record = self._history.get(key)
        count = 1 if record is None else min(255, record[0] + 1)
        self._history[key] = (count, self._tick)
        if len(self._history) > 8192:
            ordered = sorted(
                self._history,
                key=lambda item: (self._history[item][1], item),
            )
            remove_count = len(self._history) - 6144
            for old_key in ordered[:remove_count]:
                del self._history[old_key]
        return count

    def _victim_order(self):
        probation = sorted(
            self._probation,
            key=lambda item: (self._items[item][2], self._items[item][3], item),
        )
        protected = sorted(
            self._protected,
            key=lambda item: (self._items[item][2], self._items[item][3], item),
        )
        return probation + protected

    def _remove(self, key):
        entry = self._items.pop(key, None)
        if entry is None:
            return
        self._bytes -= entry[0]
        if entry[1] == 0:
            self._probation.pop(key, None)
        else:
            self._protected.pop(key, None)
            self._protected_bytes -= entry[0]

    def _protected_limit(self):
        ratio = 55 + (30 * self._pressure) // 100
        return (self.capacity_bytes * ratio) // 100

    def _rebalance(self):
        limit = self._protected_limit()
        while self._protected and self._protected_bytes > limit and len(self._protected) > 1:
            key = next(iter(self._protected))
            self._protected.pop(key)
            entry = self._items[key]
            entry[1] = 0
            self._protected_bytes -= entry[0]
            self._probation[key] = None

    def _resize_hit(self, key, entry, requested):
        old_size = entry[0]
        if requested == old_size:
            return []
        if requested < old_size:
            delta = requested - old_size
            entry[0] = requested
            self._bytes += delta
            if entry[1]:
                self._protected_bytes += delta
            return []
        needed = requested - old_size
        evicted = []
        for victim in self._victim_order():
            if needed <= 0:
                break
            if victim == key:
                continue
            needed -= self._items[victim][0]
            evicted.append(victim)
        for victim in evicted:
            self._remove(victim)
        entry[0] = requested
        self._bytes += requested - old_size
        if entry[1]:
            self._protected_bytes += requested - old_size
        self._rebalance()
        return evicted

    def access(self, key, size, now):
        if self.capacity_bytes <= 0:
            evicted = list(self._items)
            self._items.clear()
            self._probation.clear()
            self._protected.clear()
            self._protected_bytes = 0
            self._bytes = 0
            return evicted

        self._tick += 1
        self._age()
        entry = self._items.get(key)

        if entry is not None:
            self._remember(key)
            entry[2] = min(255, entry[2] + 1)
            entry[3] = self._tick
            self._pressure = min(100, self._pressure + 4)
            requested = self._size(size)
            if requested > self.capacity_bytes:
                self._remove(key)
                return [key]
            evicted = []
            if requested > 0:
                evicted = self._resize_hit(key, entry, requested)
            if entry[1] == 0:
                self._probation.pop(key, None)
                entry[1] = 1
                self._protected[key] = None
                self._protected_bytes += entry[0]
            else:
                self._protected.move_to_end(key)
            self._rebalance()
            return evicted

        requested = self._size(size)
        self._pressure = max(0, self._pressure - 2)
        if requested <= 0 or requested > self.capacity_bytes:
            self._rebalance()
            return []

        candidate_frequency = self._remember(key)
        needed = self._bytes + requested - self.capacity_bytes
        selected = []
        if needed > 0:
            remaining = needed
            for victim in self._victim_order():
                selected.append(victim)
                remaining -= self._items[victim][0]
                if remaining <= 0:
                    break
            if remaining > 0:
                self._rebalance()
                return []
            threshold = max(self._items[victim][2] for victim in selected)
            if candidate_frequency < threshold:
                self._rebalance()
                return []

        evicted = []
        for victim in selected:
            self._remove(victim)
            evicted.append(victim)
        self._items[key] = [requested, 0, max(1, candidate_frequency), self._tick]
        self._probation[key] = None
        self._bytes += requested
        self._rebalance()
        return evicted
