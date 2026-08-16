from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        try:
            self.capacity_bytes = max(0, int(capacity_bytes))
        except Exception:
            self.capacity_bytes = 0
        self._items = {}
        self._probation = OrderedDict()
        self._protected = OrderedDict()
        self._ghosts = OrderedDict()
        self._ghost_limit = 4096
        self._bytes = 0
        self._protected_bytes = 0
        self._protected_target = (self.capacity_bytes * 2) // 3

    @staticmethod
    def _size(size):
        try:
            return max(0, int(size))
        except Exception:
            return 0

    def _remember(self, key, segment):
        self._ghosts.pop(key, None)
        self._ghosts[key] = segment
        while len(self._ghosts) > self._ghost_limit:
            self._ghosts.popitem(last=False)

    def _remove(self, key, remember=True):
        record = self._items.pop(key, None)
        if record is None:
            return False
        segment = record[1]
        if segment == 0:
            self._probation.pop(key, None)
        else:
            self._protected.pop(key, None)
            self._protected_bytes -= record[0]
        self._bytes -= record[0]
        if remember:
            self._remember(key, segment)
        return True

    def _demote(self):
        if not self._protected:
            return False
        key = next(iter(self._protected))
        record = self._items[key]
        self._protected.pop(key, None)
        self._protected_bytes -= record[0]
        record[1] = 0
        self._probation[key] = None
        return True

    def _rebalance(self):
        while self._protected and self._protected_bytes > self._protected_target:
            if not self._demote():
                break

    def _adapt(self, segment):
        if self.capacity_bytes <= 0:
            return
        if segment == 0:
            delta = max(1, (self.capacity_bytes - self._protected_target) // 8)
            self._protected_target = max(0, self._protected_target - delta)
        else:
            delta = max(1, self._protected_target // 8)
            self._protected_target = min(self.capacity_bytes, self._protected_target + delta)

    def _victim(self, excluded):
        for key in self._probation:
            if key != excluded:
                return key
        for key in self._protected:
            if key != excluded:
                return key
        return None

    def _room(self, excluded):
        evicted = []
        seen = set()
        self._rebalance()
        while self._bytes > self.capacity_bytes:
            victim = self._victim(excluded)
            if victim is None or victim in seen:
                break
            seen.add(victim)
            if self._remove(victim):
                evicted.append(victim)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        del now
        requested = self._size(size)

        if key in self._items:
            record = self._items[key]
            old_size = record[0]
            record[0] = requested
            self._bytes += requested - old_size
            if record[1] == 0:
                self._probation.pop(key, None)
                record[1] = 1
                self._protected[key] = None
                self._protected_bytes += requested
            else:
                self._protected.pop(key, None)
                self._protected[key] = None
            if requested > self.capacity_bytes:
                self._remove(key)
                return [key]
            return self._room(key)

        if self.capacity_bytes <= 0 or requested > self.capacity_bytes:
            return []

        prior = self._ghosts.pop(key, None)
        if prior is not None:
            self._adapt(prior)

        self._items[key] = [requested, 0]
        self._probation[key] = None
        self._bytes += requested
        return self._room(key)
