from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probationary = OrderedDict()
        self.protected = OrderedDict()
        self.entries = {}
        self.ghost = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0
        self.protected_limit = max(1, (self.capacity_bytes * 3) // 5) if self.capacity_bytes else 0
        self.ghost_limit = max(1, min(4096, self.capacity_bytes // 64 + 1))
        self.request_count = 0
        self.hit_count = 0
        self.miss_count = 0
        self.last_now = None

    def _snapshot(self):
        return (
            tuple(self.probationary.items()),
            tuple(self.protected.items()),
            tuple(self.entries.items()),
            tuple(self.ghost.items()),
            self.used_bytes,
            self.protected_bytes,
        )

    def _restore(self, snapshot):
        probationary, protected, entries, ghost, used, protected_bytes = snapshot
        self.probationary.clear()
        self.probationary.update(probationary)
        self.protected.clear()
        self.protected.update(protected)
        self.entries.clear()
        self.entries.update(entries)
        self.ghost.clear()
        self.ghost.update(ghost)
        self.used_bytes = used
        self.protected_bytes = protected_bytes

    def _valid(self):
        if self.used_bytes < 0 or self.used_bytes > self.capacity_bytes:
            return False
        if self.protected_bytes < 0:
            return False
        if set(self.entries) != set(self.probationary) | set(self.protected):
            return False
        if set(self.probationary) & set(self.protected):
            return False
        for key, size in self.probationary.items():
            record = self.entries.get(key)
            if record is None or record[0] != size or record[1] != 0 or size <= 0:
                return False
        for key, size in self.protected.items():
            record = self.entries.get(key)
            if record is None or record[0] != size or record[1] != 1 or size <= 0:
                return False
        if self.used_bytes != sum(self.probationary.values()) + sum(self.protected.values()):
            return False
        if self.protected_bytes != sum(self.protected.values()):
            return False
        return True

    def _remember(self, key):
        self.ghost.pop(key, None)
        self.ghost[key] = None
        while len(self.ghost) > self.ghost_limit:
            self.ghost.popitem(last=False)

    def _insert_probationary(self, key, size, prior_reference):
        self.ghost.pop(key, None)
        self.probationary[key] = size
        self.entries[key] = (size, 0, 1 if prior_reference else 0)
        self.used_bytes += size

    def _promote(self, key, hits):
        size = self.probationary.pop(key)
        self.protected[key] = size
        self.protected_bytes += size
        self.entries[key] = (size, 1, hits)
        while self.protected_bytes > self.protected_limit and len(self.protected) > 1:
            old_key, old_size = self.protected.popitem(last=False)
            self.protected_bytes -= old_size
            self.probationary[old_key] = old_size
            old_hits = self.entries[old_key][2]
            self.entries[old_key] = (old_size, 0, old_hits)

    def _evict_one(self):
        if self.probationary:
            old_key, old_size = self.probationary.popitem(last=False)
            segment = 0
        elif self.protected:
            old_key, old_size = self.protected.popitem(last=False)
            self.protected_bytes -= old_size
            segment = 1
        else:
            return None
        del self.entries[old_key]
        self.used_bytes -= old_size
        self._remember(old_key)
        return old_key

    def access(self, key: int, size: int, now: int) -> list[int]:
        self.request_count += 1
        self.last_now = now
        snapshot = self._snapshot()

        if key in self.entries:
            self.hit_count += 1
            record = self.entries[key]
            stored_size, segment, hits = record
            if segment == 0:
                self.probationary.pop(key)
                hits += 1
                if hits >= 2:
                    self._promote(key, hits)
                else:
                    self.probationary[key] = stored_size
                    self.entries[key] = (stored_size, 0, hits)
            else:
                self.protected.pop(key)
                self.protected[key] = stored_size
                self.entries[key] = (stored_size, 1, hits + 1)
            if not self._valid():
                self._restore(snapshot)
            return []

        self.miss_count += 1
        if self.capacity_bytes <= 0 or size <= 0 or size > self.capacity_bytes:
            return []

        prior_reference = key in self.ghost
        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            old_key = self._evict_one()
            if old_key is None:
                self._restore(snapshot)
                return []
            evicted.append(old_key)

        self._insert_probationary(key, size, prior_reference)
        if not self._valid():
            self._restore(snapshot)
            return []
        return evicted
