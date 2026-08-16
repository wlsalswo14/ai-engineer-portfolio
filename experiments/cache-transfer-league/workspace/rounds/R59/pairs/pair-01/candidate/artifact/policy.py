from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self._items = {}
        self._probationary = OrderedDict()
        self._protected = OrderedDict()
        self._used = 0
        self._protected_bytes = 0
        self._protected_target = (self.capacity_bytes * 2) // 3

    def _remove(self, key):
        entry = self._items.pop(key)
        size = entry['size']
        if entry['segment'] == 'protected':
            self._protected.pop(key, None)
            self._protected_bytes -= size
        else:
            self._probationary.pop(key, None)
        self._used -= size
        return size

    def _rebalance(self):
        while (self._protected_bytes > self._protected_target and
               len(self._protected) > 1):
            key, _ = self._protected.popitem(last=False)
            entry = self._items[key]
            entry['segment'] = 'probationary'
            self._probationary[key] = None
            self._protected_bytes -= entry['size']

    def _victim(self, excluded):
        for bucket in (self._probationary, self._protected):
            for key in bucket:
                if key != excluded:
                    return key
        return None

    def _evict_until_fit(self, excluded):
        evicted = []
        while self._used > self.capacity_bytes:
            victim = self._victim(excluded)
            if victim is None:
                break
            self._remove(victim)
            evicted.append(victim)
        return evicted

    def access(self, key, size, now):
        del now
        incoming_size = max(0, int(size))

        if key in self._items:
            old_segment = self._items[key]['segment']
            self._remove(key)
            if incoming_size > self.capacity_bytes:
                return [key]
            if old_segment == 'protected':
                self._items[key] = {
                    'size': incoming_size,
                    'segment': 'protected',
                }
                self._protected[key] = None
                self._protected_bytes += incoming_size
            else:
                self._items[key] = {
                    'size': incoming_size,
                    'segment': 'protected',
                }
                self._protected[key] = None
                self._protected_bytes += incoming_size
            self._used += incoming_size
            self._rebalance()
            return self._evict_until_fit(key)

        if incoming_size > self.capacity_bytes:
            return []

        self._items[key] = {
            'size': incoming_size,
            'segment': 'probationary',
        }
        self._probationary[key] = None
        self._used += incoming_size
        return self._evict_until_fit(key)
