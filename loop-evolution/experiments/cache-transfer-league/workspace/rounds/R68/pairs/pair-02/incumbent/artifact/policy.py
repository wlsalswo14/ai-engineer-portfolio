from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self._resident = {}
        self._recent = OrderedDict()
        self._frequent = OrderedDict()
        self._recent_bytes = 0
        self._bytes = 0
        self._target = self.capacity // 2
        self._ghost_recent = OrderedDict()
        self._ghost_frequent = OrderedDict()
        self._ghost_limit = 2048

    def _remember(self, key, size, recent):
        self._ghost_recent.pop(key, None)
        self._ghost_frequent.pop(key, None)
        target = self._ghost_recent if recent else self._ghost_frequent
        target[key] = size
        while len(target) > self._ghost_limit:
            target.popitem(last=False)

    def _remove(self, key):
        size = self._resident.pop(key)
        if key in self._recent:
            del self._recent[key]
            self._recent_bytes -= size
        else:
            self._frequent.pop(key, None)
        self._bytes -= size
        return size

    def _evict_one(self, protected=None):
        prefer_recent = bool(self._recent) and (
            not self._frequent or self._recent_bytes > self._target
        )
        queues = (
            ((self._recent, True), (self._frequent, False))
            if prefer_recent
            else ((self._frequent, False), (self._recent, True))
        )
        for queue, is_recent in queues:
            victim = next((k for k in queue if k != protected), None)
            if victim is not None:
                size = self._remove(victim)
                self._remember(victim, size, is_recent)
                return victim
        return None

    def _make_room(self, needed, protected=None):
        evicted = []
        while self._bytes + needed > self.capacity:
            victim = self._evict_one(protected)
            if victim is None:
                break
            evicted.append(victim)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        item_size = max(0, int(size))

        if key in self._resident:
            old_size = self._resident[key]
            if item_size > self.capacity:
                was_recent = key in self._recent
                removed_size = self._remove(key)
                self._remember(key, removed_size, was_recent)
                return [key]

            if key in self._recent:
                del self._recent[key]
                self._recent_bytes -= old_size
                self._frequent[key] = None
            else:
                self._frequent.move_to_end(key)

            delta = item_size - old_size
            evicted = self._make_room(delta, key) if delta > 0 else []
            if self._bytes + delta > self.capacity:
                was_recent = False
                removed_size = self._remove(key)
                self._remember(key, removed_size, was_recent)
                return evicted + [key]

            self._resident[key] = item_size
            self._bytes += delta
            return evicted

        in_recent_ghost = key in self._ghost_recent
        in_frequent_ghost = key in self._ghost_frequent
        if in_recent_ghost:
            self._ghost_recent.pop(key, None)
            step = max(1, min(self.capacity, item_size))
            self._target = min(self.capacity, self._target + step)
        elif in_frequent_ghost:
            self._ghost_frequent.pop(key, None)
            step = max(1, min(self.capacity, item_size))
            self._target = max(0, self._target - step)

        if item_size > self.capacity:
            return []

        evicted = self._make_room(item_size)
        if self._bytes + item_size > self.capacity:
            return evicted

        self._resident[key] = item_size
        self._bytes += item_size
        if in_recent_ghost or in_frequent_ghost:
            self._frequent[key] = None
        else:
            self._recent[key] = None
            self._recent_bytes += item_size
        return evicted
