from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        if type(capacity_bytes) is not int:
            raise TypeError("capacity_bytes must be an integer")
        self.capacity_bytes = max(0, capacity_bytes)
        self._entries = {}
        self._probation = OrderedDict()
        self._protected = OrderedDict()
        self._used = 0
        self._protected_used = 0

    def access(self, key, size, now):
        if type(key) is not int or type(size) is not int or size < 0:
            return []

        if key in self._entries:
            entry_size, segment = self._entries[key]
            if segment == "probation":
                del self._probation[key]
                self._protected[key] = None
                self._entries[key] = (entry_size, "protected")
                self._protected_used += entry_size
                self._rebalance_protected()
            else:
                self._protected.move_to_end(key)
            return []

        if size > self.capacity_bytes:
            return []

        self._entries[key] = (size, "probation")
        self._probation[key] = None
        self._used += size

        evicted = []
        reported = set()
        while self._used > self.capacity_bytes:
            if self._probation:
                victim, _ = self._probation.popitem(last=False)
            elif self._protected:
                victim, _ = self._protected.popitem(last=False)
            else:
                break

            victim_size, victim_segment = self._entries.pop(victim)
            self._used -= victim_size
            if victim_segment == "protected":
                self._protected_used -= victim_size
            if type(victim) is int and victim not in reported:
                reported.add(victim)
                evicted.append(victim)

        return evicted

    def _rebalance_protected(self):
        protected_limit = (self.capacity_bytes * 3) // 4
        while self._protected and self._protected_used > protected_limit:
            key, _ = self._protected.popitem(last=False)
            size, _ = self._entries[key]
            self._entries[key] = (size, "probation")
            self._probation[key] = None
            self._protected_used -= size
