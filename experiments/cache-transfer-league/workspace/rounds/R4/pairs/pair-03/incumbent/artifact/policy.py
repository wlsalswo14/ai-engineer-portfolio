from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.recent_ghost = OrderedDict()
        self.frequent_ghost = OrderedDict()
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.recent_ghost_bytes = 0
        self.frequent_ghost_bytes = 0
        self.target_recent = 0

    def _remove_ghost(self, table, key, recent):
        if key not in table:
            return
        size = table.pop(key)
        if recent:
            self.recent_ghost_bytes -= size
        else:
            self.frequent_ghost_bytes -= size

    def _record_ghost(self, key, size, recent):
        other = self.frequent_ghost if recent else self.recent_ghost
        self._remove_ghost(other, key, not recent)
        table = self.recent_ghost if recent else self.frequent_ghost
        self._remove_ghost(table, key, recent)
        table[key] = size
        if recent:
            self.recent_ghost_bytes += size
        else:
            self.frequent_ghost_bytes += size
        while self.recent_ghost_bytes + self.frequent_ghost_bytes > self.capacity_bytes:
            if self.recent_ghost and (
                not self.frequent_ghost or
                self.recent_ghost_bytes >= self.frequent_ghost_bytes
            ):
                old_key, old_size = self.recent_ghost.popitem(last=False)
                self.recent_ghost_bytes -= old_size
            elif self.frequent_ghost:
                old_key, old_size = self.frequent_ghost.popitem(last=False)
                self.frequent_ghost_bytes -= old_size
            else:
                break

    def _take_recent(self):
        key, size = self.recent.popitem(last=False)
        self.recent_bytes -= size
        self._record_ghost(key, size, True)
        return key

    def _take_frequent(self):
        key, size = self.frequent.popitem(last=False)
        self.frequent_bytes -= size
        self._record_ghost(key, size, False)
        return key

    def _replace_one(self, from_frequent):
        choose_recent = bool(self.recent) and (
            self.recent_bytes > self.target_recent or
            (from_frequent and self.recent_bytes == self.target_recent)
        )
        if choose_recent:
            return self._take_recent()
        if self.frequent:
            return self._take_frequent()
        if self.recent:
            return self._take_recent()
        return None

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.frequent:
            stored_size = self.frequent.pop(key)
            self.frequent[key] = stored_size
            return []

        if key in self.recent:
            stored_size = self.recent.pop(key)
            self.recent_bytes -= stored_size
            self.frequent[key] = stored_size
            self.frequent_bytes += stored_size
            return []

        if size <= 0 or size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        from_frequent = key in self.frequent_ghost
        from_recent = key in self.recent_ghost

        if from_recent:
            self._remove_ghost(self.recent_ghost, key, True)
            self.target_recent = min(
                self.capacity_bytes,
                self.target_recent + size,
            )
        elif from_frequent:
            self._remove_ghost(self.frequent_ghost, key, False)
            self.target_recent = max(0, self.target_recent - size)

        evicted = []
        while self.recent_bytes + self.frequent_bytes + size > self.capacity_bytes:
            victim = self._replace_one(from_frequent)
            if victim is None:
                break
            evicted.append(victim)

        if from_recent or from_frequent:
            self.frequent[key] = size
            self.frequent_bytes += size
        else:
            self.recent[key] = size
            self.recent_bytes += size

        return evicted
