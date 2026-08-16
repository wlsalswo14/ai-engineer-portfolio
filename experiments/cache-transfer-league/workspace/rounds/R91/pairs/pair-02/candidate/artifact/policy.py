from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        if type(capacity_bytes) is int:
            self.capacity_bytes = max(0, capacity_bytes)
        else:
            self.capacity_bytes = 0
        self.used_bytes = 0
        self._items = {}
        self._probationary = OrderedDict()
        self._protected = OrderedDict()
        self._protected_bytes = 0
        self._history = OrderedDict()
        self._history_limit = 4096
        self._tick = 0

    def _record(self, key):
        previous = self._history.pop(key, None)
        count = 1 if previous is None else min(previous[0] + 1, 255)
        self._history[key] = (count, self._tick)
        while len(self._history) > self._history_limit:
            self._history.popitem(last=False)
        return count

    def _remove(self, key):
        item = self._items.pop(key, None)
        if item is None:
            return
        self.used_bytes -= item[0]
        if item[1]:
            self._protected.pop(key, None)
            self._protected_bytes -= item[0]
        else:
            self._probationary.pop(key, None)

    def _choose_victim(self, avoid=None):
        for pool in (self._probationary, self._protected):
            for key in pool:
                if key != avoid:
                    return key
        return None

    def _make_room(self, required, evicted, avoid=None):
        while self.used_bytes + required > self.capacity_bytes:
            victim = self._choose_victim(avoid)
            if victim is None:
                return False
            self._remove(victim)
            if victim not in evicted:
                evicted.append(victim)
        return True

    def _rebalance_protected(self):
        target = self.capacity_bytes // 2
        while self._protected and self._protected_bytes > target:
            key, _ = self._protected.popitem(last=False)
            item = self._items[key]
            item[1] = 0
            self._protected_bytes -= item[0]
            self._probationary[key] = None

    def access(self, key, size, now):
        self._tick += 1
        evicted = []
        if type(key) is not int or type(size) is not int or size <= 0:
            return evicted

        history_count = self._record(key)
        item = self._items.get(key)

        if size > self.capacity_bytes:
            if item is not None:
                self._remove(key)
                evicted.append(key)
            return evicted

        if item is not None:
            delta = size - item[0]
            if delta > 0 and not self._make_room(delta, evicted, key):
                self._remove(key)
                evicted.append(key)
                return evicted
            self.used_bytes += delta
            item[0] = size
            item[2] = min(item[2] + 1, 255)
            item[3] = self._tick
            if item[1]:
                self._protected_bytes += delta
                self._protected.move_to_end(key)
            else:
                self._probationary.pop(key, None)
                item[1] = 1
                self._protected[key] = None
                self._protected_bytes += size
            self._rebalance_protected()
            return evicted

        if not self._make_room(size, evicted):
            return evicted

        protected = history_count >= 2
        self._items[key] = [size, 1 if protected else 0, history_count, self._tick]
        self.used_bytes += size
        if protected:
            self._protected[key] = None
            self._protected_bytes += size
            self._rebalance_protected()
        else:
            self._probationary[key] = None
        return evicted
