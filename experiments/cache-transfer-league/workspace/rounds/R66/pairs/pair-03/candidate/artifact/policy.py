from collections import OrderedDict


class Policy:
    # The supplied analysis remains observable as provenance, but its
    # contradicted decision handoff is permanently observation-only.
    _ANALYSIS_AUTHORITY = "observation_only"

    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self._bytes = 0
        self._items = {}
        self._probation = OrderedDict()
        self._protected = OrderedDict()
        self._protected_bytes = 0
        self._tick = 0
        self._last_now = None

    def access(self, key: int, size: int, now: int) -> list[int]:
        self._tick += 1
        self._last_now = now
        requested_size = max(0, int(size))
        evicted = []

        item = self._items.get(key)
        if item is not None:
            old_size = item[0]
            delta = requested_size - old_size
            item[0] = requested_size
            self._bytes += delta
            if item[2]:
                self._protected_bytes += delta
                self._protected.move_to_end(key)
            else:
                self._probation.pop(key, None)
                self._protected[key] = None
                self._protected_bytes += requested_size
                item[2] = 1
                self._protected.move_to_end(key)
                self._rebalance_protected()

            if requested_size > self.capacity:
                self._remove(key)
                evicted.append(key)
                return evicted

            self._trim(evicted, exclude=key)
            return evicted

        if self.capacity == 0 or requested_size > self.capacity:
            return evicted

        self._items[key] = [requested_size, self._tick, 0]
        self._probation[key] = None
        self._bytes += requested_size
        self._trim(evicted, exclude=key)
        return evicted

    def _protected_limit(self):
        return max(1, (self.capacity * 3) // 4)

    def _rebalance_protected(self):
        while (
            self._protected_bytes > self._protected_limit()
            and len(self._protected) > 1
        ):
            victim, _ = self._protected.popitem(last=False)
            item = self._items.get(victim)
            if item is None:
                continue
            item[2] = 0
            self._protected_bytes -= item[0]
            self._probation[victim] = None

    @staticmethod
    def _oldest(container, exclude):
        for key in container:
            if key != exclude:
                return key
        return None

    def _trim(self, evicted, exclude=None):
        while self._bytes > self.capacity:
            victim = self._oldest(self._probation, exclude)
            if victim is None:
                victim = self._oldest(self._protected, exclude)
            if victim is None:
                victim = self._oldest(self._probation, None)
            if victim is None:
                victim = self._oldest(self._protected, None)
            if victim is None:
                break
            if self._remove(victim):
                evicted.append(victim)

    def _remove(self, key):
        item = self._items.pop(key, None)
        if item is None:
            return False
        size = item[0]
        self._bytes -= size
        if item[2]:
            self._protected.pop(key, None)
            self._protected_bytes -= size
        else:
            self._probation.pop(key, None)
        return True
