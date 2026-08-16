from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self._items = {}
        self._probation = OrderedDict()
        self._protected = OrderedDict()
        self._ghost_probation = OrderedDict()
        self._ghost_protected = OrderedDict()
        self._used = 0
        self._protected_bytes = 0
        self._protected_target = (self.capacity_bytes * 3) // 5
        self._ghost_limit = 4096

    def _remember(self, ghost, key):
        ghost.pop(key, None)
        ghost[key] = None
        while len(ghost) > self._ghost_limit:
            ghost.popitem(last=False)

    def _remove(self, key, ghost_segment=None):
        item = self._items.pop(key, None)
        if item is None:
            return
        size, segment = item
        if segment == 1:
            self._protected.pop(key, None)
            self._protected_bytes -= size
        else:
            self._probation.pop(key, None)
        self._used -= size
        if ghost_segment == 0:
            self._remember(self._ghost_probation, key)
        elif ghost_segment == 1:
            self._remember(self._ghost_protected, key)

    def _rebalance_protected(self):
        while self._protected and self._protected_bytes > self._protected_target:
            key, _ = self._protected.popitem(last=False)
            item = self._items.get(key)
            if item is None:
                continue
            size, _ = item
            item[1] = 0
            self._probation[key] = None
            self._protected_bytes -= size

    def _evict_until(self, incoming_size, evicted):
        while self._items and self._used + incoming_size > self.capacity_bytes:
            if self._probation:
                key = next(iter(self._probation))
                self._remove(key, 0)
            else:
                key = next(iter(self._protected))
                self._remove(key, 1)
            evicted.append(key)

    def _adjust_from_ghost(self, key):
        step = max(1, self.capacity_bytes // 16)
        if key in self._ghost_probation:
            self._ghost_probation.pop(key, None)
            self._ghost_protected.pop(key, None)
            self._protected_target = min(self.capacity_bytes, self._protected_target + step)
        elif key in self._ghost_protected:
            self._ghost_protected.pop(key, None)
            self._ghost_probation.pop(key, None)
            self._protected_target = max(0, self._protected_target - step)
        self._rebalance_protected()

    def access(self, key: int, size: int, now: int) -> list[int]:
        del now
        size = max(0, int(size))
        item = self._items.get(key)
        if item is not None:
            if item[1] == 1:
                self._protected.move_to_end(key)
            else:
                self._probation.pop(key, None)
                item[1] = 1
                self._protected[key] = None
                self._protected_bytes += item[0]
                self._rebalance_protected()
            return []

        self._adjust_from_ghost(key)
        evicted = []
        self._evict_until(size, evicted)
        if size > self.capacity_bytes:
            return evicted

        self._ghost_probation.pop(key, None)
        self._ghost_protected.pop(key, None)
        self._items[key] = [size, 0]
        self._probation[key] = None
        self._used += size
        return evicted
