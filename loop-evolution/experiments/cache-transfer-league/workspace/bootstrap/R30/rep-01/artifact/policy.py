from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probationary = OrderedDict()
        self.protected = OrderedDict()
        self._where = {}
        self.used_bytes = 0
        self._protected_bytes = 0
        self.request_count = 0
        self.hit_count = 0
        self.miss_count = 0
        self.eviction_count = 0
        self.promotion_count = 0

    def _protected_limit(self):
        if self.capacity_bytes <= 0:
            return 0
        return max(1, (self.capacity_bytes * 3) // 5)

    def _trim_protected(self):
        limit = self._protected_limit()
        while self._protected_bytes > limit and len(self.protected) > 1:
            old_key, old_size = self.protected.popitem(last=False)
            self._protected_bytes -= old_size
            self.probationary[old_key] = old_size
            self._where[old_key] = 0

    def _remove_oldest(self, segment):
        old_key, old_size = segment.popitem(last=False)
        self._where.pop(old_key, None)
        self.used_bytes -= old_size
        if segment is self.protected:
            self._protected_bytes -= old_size
        self.eviction_count += 1
        return old_key

    def _make_room(self, size, evicted):
        self._trim_protected()
        while self.used_bytes + size > self.capacity_bytes:
            if self.probationary:
                evicted.append(self._remove_oldest(self.probationary))
            elif self.protected:
                evicted.append(self._remove_oldest(self.protected))
            else:
                break

    def _promote(self, key):
        stored_size = self.probationary.pop(key)
        self.protected[key] = stored_size
        self._where[key] = 1
        self._protected_bytes += stored_size
        self.promotion_count += 1
        self._trim_protected()

    def _touch_protected(self, key):
        stored_size = self.protected.pop(key)
        self.protected[key] = stored_size

    def access(self, key: int, size: int, now: int) -> list[int]:
        self.request_count += 1
        location = self._where.get(key)
        if location == 1:
            self._touch_protected(key)
            self.hit_count += 1
            return []
        if location == 0:
            self._promote(key)
            self.hit_count += 1
            return []

        self.miss_count += 1
        if size > self.capacity_bytes:
            return []

        evicted = []
        self._make_room(size, evicted)
        self.probationary[key] = size
        self._where[key] = 0
        self.used_bytes += size
        return evicted
