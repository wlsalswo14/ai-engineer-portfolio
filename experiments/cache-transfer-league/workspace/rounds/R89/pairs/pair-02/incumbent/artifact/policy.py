from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        self.capacity = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.used = 0
        self.target = self.capacity // 2
        self.ghost_bytes = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096
        self.serial = 0

    def _discard_ghost(self, key):
        value = self.ghost_recent.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]
        value = self.ghost_frequent.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, kind):
        self._discard_ghost(key)
        self.serial += 1
        value = (max(1, int(size)), self.serial)
        if kind == 1:
            self.ghost_recent[key] = value
        else:
            self.ghost_frequent[key] = value
        self.ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_recent) + len(self.ghost_frequent) > self.ghost_count_limit):
            source = None
            oldest = None
            for table in (self.ghost_recent, self.ghost_frequent):
                if table:
                    value = next(iter(table.values()))
                    if oldest is None or value[1] < oldest[1]:
                        oldest = value
                        source = table
            if source is None:
                break
            _, value = source.popitem(last=False)
            self.ghost_bytes -= value[0]

    def _adapt_target(self, kind):
        if self.capacity <= 0:
            return
        recent = sum(value[0] for value in self.ghost_recent.values())
        frequent = sum(value[0] for value in self.ghost_frequent.values())
        if kind == 1:
            delta = self.capacity if recent == 0 else max(1, min(self.capacity, frequent // recent or 1))
            self.target = max(0, self.target - delta)
        else:
            delta = self.capacity if frequent == 0 else max(1, min(self.capacity, recent // frequent or 1))
            self.target = min(self.capacity, self.target + delta)

    def _demote_frequent(self):
        if not self.frequent:
            return False
        key, size = self.frequent.popitem(last=False)
        self.frequent_bytes -= size
        self.recent[key] = (size, 2)
        self.recent_bytes += size
        return True

    def _evict_recent(self):
        if not self.recent:
            return None
        key, value = self.recent.popitem(last=False)
        size, origin = value
        self.recent_bytes -= size
        self.used -= size
        self._remember_ghost(key, size, origin)
        return key

    def _make_room(self, incoming, frequent_admission):
        evicted = []
        if frequent_admission:
            limit = max(self.target, incoming)
            while self.frequent and self.frequent_bytes + incoming > limit:
                self._demote_frequent()
        while self.used + incoming > self.capacity:
            key = self._evict_recent()
            if key is not None:
                evicted.append(key)
            elif not self._demote_frequent():
                break
        return evicted

    def _unique(self, keys):
        result = []
        seen = set()
        for key in keys:
            if key not in seen:
                seen.add(key)
                result.append(key)
        return result

    def access(self, key, size, now):
        key = int(key)
        size = max(0, int(size))

        if key in self.recent:
            old_size, _ = self.recent.pop(key)
            self.recent_bytes -= old_size
            self.used -= old_size
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, True)
            if self.used + size > self.capacity:
                return self._unique(evicted + [key])
            self._discard_ghost(key)
            self.frequent[key] = size
            self.frequent_bytes += size
            self.used += size
            return self._unique(evicted)

        if key in self.frequent:
            old_size = self.frequent.pop(key)
            self.frequent_bytes -= old_size
            self.used -= old_size
            if size <= 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, True)
            if self.used + size > self.capacity:
                return self._unique(evicted + [key])
            self._discard_ghost(key)
            self.frequent[key] = size
            self.frequent_bytes += size
            self.used += size
            return self._unique(evicted)

        ghost_kind = 1 if key in self.ghost_recent else 2 if key in self.ghost_frequent else 0
        if size <= 0 or size > self.capacity:
            return []
        if ghost_kind:
            self._adapt_target(ghost_kind)
            self._discard_ghost(key)

        evicted = self._make_room(size, ghost_kind == 2)
        if self.used + size > self.capacity:
            return self._unique(evicted)
        if ghost_kind == 2:
            self.frequent[key] = size
            self.frequent_bytes += size
        else:
            self.recent[key] = (size, 1)
            self.recent_bytes += size
        self.used += size
        return self._unique(evicted)
