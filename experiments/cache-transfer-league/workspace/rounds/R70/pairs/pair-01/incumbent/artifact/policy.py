from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.ghost_recent_bytes = 0
        self.ghost_frequent_bytes = 0
        self.recent_target = self.capacity // 2
        self.ghost_max_bytes = max(1, self.capacity * 2)
        self.ghost_max_count = max(16, min(4096, self.capacity // 64 + 64))

    def _drop_ghost(self, key):
        if key in self.ghost_recent:
            self.ghost_recent_bytes -= self.ghost_recent.pop(key)
        if key in self.ghost_frequent:
            self.ghost_frequent_bytes -= self.ghost_frequent.pop(key)

    def _remember_ghost(self, segment, key, size):
        self._drop_ghost(key)
        if segment == "recent":
            self.ghost_recent[key] = size
            self.ghost_recent_bytes += size
        else:
            self.ghost_frequent[key] = size
            self.ghost_frequent_bytes += size
        while (len(self.ghost_recent) + len(self.ghost_frequent) > self.ghost_max_count or
               self.ghost_recent_bytes + self.ghost_frequent_bytes > self.ghost_max_bytes):
            if self.ghost_recent:
                old_key, old_size = self.ghost_recent.popitem(last=False)
                self.ghost_recent_bytes -= old_size
            elif self.ghost_frequent:
                old_key, old_size = self.ghost_frequent.popitem(last=False)
                self.ghost_frequent_bytes -= old_size
            else:
                break

    def _take_recent(self, key):
        size = self.recent.pop(key)
        self.recent_bytes -= size
        return size

    def _take_frequent(self, key):
        size = self.frequent.pop(key)
        self.frequent_bytes -= size
        return size

    def _put_recent(self, key, size):
        self.recent[key] = size
        self.recent_bytes += size

    def _put_frequent(self, key, size):
        self.frequent[key] = size
        self.frequent_bytes += size

    def _choose_victim(self, protected):
        prefer_recent = self.recent and (self.recent_bytes > self.recent_target or not self.frequent)
        groups = ((self.recent, "recent"), (self.frequent, "frequent")) if prefer_recent else ((self.frequent, "frequent"), (self.recent, "recent"))
        for group, segment in groups:
            for key in group:
                if key != protected:
                    return segment, key
        return None

    def _make_room(self, extra, protected=None):
        evicted = []
        while self.recent_bytes + self.frequent_bytes + extra > self.capacity:
            victim = self._choose_victim(protected)
            if victim is None:
                break
            segment, key = victim
            size = self._take_recent(key) if segment == "recent" else self._take_frequent(key)
            self._remember_ghost(segment, key, size)
            evicted.append(key)
        return evicted

    def _adapt_target(self, segment, old_size, new_size):
        if not self.capacity:
            self.recent_target = 0
            return
        delta = max(1, min(self.capacity, max(1, old_size, new_size)))
        if segment == "recent":
            self.recent_target = min(self.capacity, self.recent_target + delta)
        else:
            self.recent_target = max(0, self.recent_target - delta)

    def access(self, key: int, size: int, now: int) -> list[int]:
        del now
        incoming_size = max(0, int(size))

        if key in self.recent:
            self._take_recent(key)
            if incoming_size > self.capacity:
                self._remember_ghost("frequent", key, incoming_size)
                return [key]
            self._put_frequent(key, incoming_size)
            return self._make_room(0, protected=key)

        if key in self.frequent:
            self._take_frequent(key)
            if incoming_size > self.capacity:
                self._remember_ghost("frequent", key, incoming_size)
                return [key]
            self._put_frequent(key, incoming_size)
            return self._make_room(0, protected=key)

        ghost_segment = None
        ghost_size = 0
        if key in self.ghost_recent:
            ghost_segment = "recent"
            ghost_size = self.ghost_recent[key]
        elif key in self.ghost_frequent:
            ghost_segment = "frequent"
            ghost_size = self.ghost_frequent[key]

        if ghost_segment is not None:
            self._drop_ghost(key)
            self._adapt_target(ghost_segment, ghost_size, incoming_size)

        if self.capacity <= 0 or incoming_size > self.capacity:
            return []

        evicted = self._make_room(incoming_size)
        if ghost_segment is None:
            self._put_recent(key, incoming_size)
        else:
            self._put_frequent(key, incoming_size)
        return evicted
