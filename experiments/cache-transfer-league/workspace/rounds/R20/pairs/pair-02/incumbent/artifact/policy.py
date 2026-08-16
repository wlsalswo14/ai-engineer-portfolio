from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.protected_target = self.capacity_bytes // 2
        self.used_bytes = 0

    def _discard_ghost(self, key):
        self.ghost_recent.pop(key, None)
        self.ghost_frequent.pop(key, None)

    def _record_ghost(self, key, size, frequent):
        self._discard_ghost(key)
        target = self.ghost_frequent if frequent else self.ghost_recent
        target[key] = size
        while sum(self.ghost_recent.values()) + sum(self.ghost_frequent.values()) > self.capacity_bytes:
            if self.ghost_recent:
                self.ghost_recent.popitem(last=False)
            elif self.ghost_frequent:
                self.ghost_frequent.popitem(last=False)
            else:
                break

    def _demote_frequent(self):
        while self.frequent and sum(self.frequent.values()) > self.protected_target:
            key, size = self.frequent.popitem(last=False)
            self.recent[key] = size

    def _evict_one(self):
        if self.recent:
            key, size = self.recent.popitem(last=False)
            self._record_ghost(key, size, False)
        elif self.frequent:
            key, size = self.frequent.popitem(last=False)
            self._record_ghost(key, size, True)
        else:
            return None
        self.used_bytes -= size
        return key

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.frequent:
            stored_size = self.frequent.pop(key)
            self.frequent[key] = stored_size
            return []

        if key in self.recent:
            stored_size = self.recent.pop(key)
            self.frequent[key] = stored_size
            self._demote_frequent()
            return []

        if self.capacity_bytes == 0 or size <= 0 or size > self.capacity_bytes:
            self._discard_ghost(key)
            return []

        if key in self.ghost_recent:
            self.ghost_recent.pop(key)
            self.protected_target = min(
                self.capacity_bytes,
                self.protected_target + max(1, min(size, self.capacity_bytes)),
            )
            destination = self.frequent
        elif key in self.ghost_frequent:
            self.ghost_frequent.pop(key)
            self.protected_target = max(
                0,
                self.protected_target - max(1, min(size, self.capacity_bytes)),
            )
            destination = self.frequent
        else:
            destination = self.recent

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            victim = self._evict_one()
            if victim is None:
                break
            evicted.append(victim)

        destination[key] = size
        self.used_bytes += size
        self._demote_frequent()
        return evicted
