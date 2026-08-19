from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.used_bytes = 0
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.recent_ghost = OrderedDict()
        self.frequent_ghost = OrderedDict()
        self.tick = 0
        low, high = self._bounds()
        self.protected_limit = min(high, max(low, (self.capacity_bytes * 3) // 5))
        self.ghost_limit = 2048

    def _bounds(self):
        low = self.capacity_bytes // 4
        high = max(low, (self.capacity_bytes * 3) // 4)
        return low, high

    def _remember_ghost(self, table, key):
        self.recent_ghost.pop(key, None)
        self.frequent_ghost.pop(key, None)
        table[key] = None
        while len(table) > self.ghost_limit:
            table.popitem(last=False)

    def _rebalance(self):
        total = sum(record['size'] for record in self.protected.values())
        while self.protected and total > self.protected_limit:
            key, record = self.protected.popitem(last=False)
            self.probation[key] = record
            total -= record['size']

    def _pick_victim(self, table):
        if not table:
            return None
        items = list(table.items())[:96]
        victim_key, victim = items[0]
        victim_value = (victim['hits'] + 1) * max(1, victim['size'])
        for key, record in items[1:]:
            value = (record['hits'] + 1) * max(1, record['size'])
            if value < victim_value or (value == victim_value and record['last'] < victim['last']):
                victim_key, victim, victim_value = key, record, value
        table.pop(victim_key)
        return victim_key, victim

    def _evict_one(self, evicted):
        candidate = self._pick_victim(self.probation)
        if candidate is not None:
            key, record = candidate
            self._remember_ghost(self.recent_ghost, key)
        else:
            candidate = self._pick_victim(self.protected)
            if candidate is None:
                return False
            key, record = candidate
            self._remember_ghost(self.frequent_ghost, key)
        self.used_bytes -= record['size']
        evicted.append(key)
        return True

    def access(self, key: int, size: int, now: int) -> list[int]:
        self.tick += 1

        record = self.protected.get(key)
        if record is not None:
            record['hits'] = min(255, record['hits'] + 1)
            record['last'] = self.tick
            self.protected.move_to_end(key)
            return []

        record = self.probation.get(key)
        if record is not None:
            self.probation.pop(key)
            record['hits'] = min(255, record['hits'] + 1)
            record['last'] = self.tick
            self.protected[key] = record
            self._rebalance()
            return []

        try:
            incoming = int(size)
        except (TypeError, ValueError, OverflowError):
            return []
        if self.capacity_bytes == 0 or incoming < 0 or incoming > self.capacity_bytes:
            return []

        low, high = self._bounds()
        step = max(1, self.capacity_bytes // 16)
        if key in self.recent_ghost:
            self.protected_limit = max(low, self.protected_limit - step)
        elif key in self.frequent_ghost:
            self.protected_limit = min(high, self.protected_limit + step)
        self.recent_ghost.pop(key, None)
        self.frequent_ghost.pop(key, None)
        self._rebalance()

        evicted = []
        while self.used_bytes + incoming > self.capacity_bytes:
            if not self._evict_one(evicted):
                break
        if self.used_bytes + incoming > self.capacity_bytes:
            return evicted

        self.probation[key] = {'size': incoming, 'hits': 0, 'last': self.tick}
        self.used_bytes += incoming
        self._rebalance()
        return evicted
