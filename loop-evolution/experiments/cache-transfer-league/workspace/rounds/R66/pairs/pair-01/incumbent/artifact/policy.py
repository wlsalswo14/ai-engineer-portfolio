from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self._bytes = 0
        self._recent_bytes = 0
        self._protected_bytes = 0
        self._recent_target = max(1, self.capacity // 5) if self.capacity else 0
        self._protected_target = self.capacity - self._recent_target
        self._entries = {}
        self._recent = OrderedDict()
        self._protected = OrderedDict()
        self._ghost = OrderedDict()
        self._frequency = OrderedDict()
        self._ticks = 0

    def _count(self, key, extra=0):
        value = self._frequency.get(key, 0)
        value = min(255, value + 1 + extra)
        self._frequency[key] = value
        self._frequency.move_to_end(key)
        while len(self._frequency) > 8192:
            self._frequency.popitem(last=False)
        return value

    def _age(self):
        for key in list(self._frequency):
            self._frequency[key] = max(1, self._frequency[key] // 2)
        for entry in self._entries.values():
            entry[1] = max(1, entry[1] // 2)

    def _remember_ghost(self, key):
        self._ghost[key] = None
        self._ghost.move_to_end(key)
        while len(self._ghost) > 4096:
            self._ghost.popitem(last=False)

    def _remove(self, key):
        entry = self._entries.pop(key, None)
        if entry is None:
            return
        size, _, segment = entry
        self._bytes -= size
        if segment == 0:
            self._recent.pop(key, None)
            self._recent_bytes -= size
        else:
            self._protected.pop(key, None)
            self._protected_bytes -= size
        self._remember_ghost(key)

    def _victim_order(self, incoming_size, exclude):
        recent_first = self._recent_bytes + incoming_size > self._recent_target
        stores = (self._recent, self._protected) if recent_first else (self._protected, self._recent)
        for store in stores:
            for key in store:
                if key != exclude:
                    yield key

    def _plan(self, incoming_size, exclude=None):
        required = self._bytes + incoming_size - self.capacity
        if required <= 0:
            return []
        planned = []
        freed = 0
        for key in self._victim_order(incoming_size, exclude):
            planned.append(key)
            freed += self._entries[key][0]
            if freed >= required:
                break
        return planned

    def _make_room(self, incoming_size, exclude=None):
        evicted = []
        for key in self._plan(incoming_size, exclude):
            self._remove(key)
            evicted.append(key)
        return evicted

    def _rebalance_protected(self):
        while self._protected and self._protected_bytes > self._protected_target:
            key, _ = self._protected.popitem(last=False)
            entry = self._entries.get(key)
            if entry is None:
                continue
            size = entry[0]
            entry[2] = 0
            self._protected_bytes -= size
            self._recent[key] = None
            self._recent_bytes += size

    def access(self, key: int, size: int, now: int) -> list[int]:
        del now
        incoming = max(0, int(size))
        self._ticks += 1
        if self._ticks % 2048 == 0:
            self._age()

        entry = self._entries.get(key)
        if entry is not None:
            if incoming > self.capacity:
                self._remove(key)
                return [key]
            old_size = entry[0]
            self._bytes += incoming - old_size
            entry[0] = incoming
            entry[1] = self._count(key)
            if entry[2] == 0:
                self._recent.pop(key, None)
                self._recent_bytes -= incoming
                entry[2] = 1
                self._protected[key] = None
                self._protected_bytes += incoming
                self._rebalance_protected()
            else:
                self._protected.move_to_end(key)
            return self._make_room(0, key)

        if incoming > self.capacity:
            return []

        ghost_hit = key in self._ghost
        if ghost_hit:
            del self._ghost[key]
        count = self._count(key, 1 if ghost_hit else 0)
        evicted = self._make_room(incoming)

        if ghost_hit:
            self._entries[key] = [incoming, count, 1]
            self._protected[key] = None
            self._protected_bytes += incoming
        else:
            self._entries[key] = [incoming, count, 0]
            self._recent[key] = None
            self._recent_bytes += incoming
        self._bytes += incoming
        self._rebalance_protected()
        return evicted
