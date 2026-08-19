from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self._probation = OrderedDict()
        self._protected = OrderedDict()
        self._probation_bytes = 0
        self._protected_bytes = 0

    def _rebalance_protected(self):
        while 2 * self._protected_bytes > self.capacity_bytes and self._protected:
            key, size = self._protected.popitem(last=False)
            self._protected_bytes -= size
            self._probation[key] = size
            self._probation_bytes += size
            self._probation.move_to_end(key, last=False)

    def _trim_capacity(self, evicted):
        while self._probation_bytes + self._protected_bytes > self.capacity_bytes:
            if self._probation:
                key, size = self._probation.popitem(last=False)
                self._probation_bytes -= size
                evicted.append(key)
            elif self._protected:
                key, size = self._protected.popitem(last=False)
                self._protected_bytes -= size
                evicted.append(key)
            else:
                break

    def access(self, key, size, now):
        del now
        size = max(0, int(size))
        evicted = []

        if key in self._protected:
            old_size = self._protected.pop(key)
            self._protected_bytes -= old_size
            if size > self.capacity_bytes:
                evicted.append(key)
                return evicted
            self._protected[key] = size
            self._protected_bytes += size
            self._rebalance_protected()
            self._trim_capacity(evicted)
            return evicted

        if key in self._probation:
            old_size = self._probation.pop(key)
            self._probation_bytes -= old_size
            if size > self.capacity_bytes:
                evicted.append(key)
                return evicted
            self._protected[key] = size
            self._protected_bytes += size
            self._rebalance_protected()
            self._trim_capacity(evicted)
            return evicted

        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            return evicted

        self._probation[key] = size
        self._probation_bytes += size
        self._rebalance_protected()
        self._trim_capacity(evicted)
        return evicted
