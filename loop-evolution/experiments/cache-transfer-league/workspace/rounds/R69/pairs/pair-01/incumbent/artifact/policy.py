from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self._capacity = max(0, int(capacity_bytes))
        self._recent = OrderedDict()
        self._frequent = OrderedDict()
        self._recent_ghost = OrderedDict()
        self._frequent_ghost = OrderedDict()
        self._recent_bytes = 0
        self._frequent_bytes = 0
        self._resident_bytes = 0
        self._recent_target = self._capacity // 2
        self._ghost_bytes = 0
        self._ghost_serial = 0
        self._ghost_limit = 4096

    def _segment(self, kind):
        return self._recent if kind == 0 else self._frequent

    def _remove_resident(self, kind, key):
        segment = self._segment(kind)
        value = segment.pop(key)
        if kind == 0:
            self._recent_bytes -= value
        else:
            self._frequent_bytes -= value
        self._resident_bytes -= value
        return value

    def _take_ghost(self, key):
        for kind, segment in ((0, self._recent_ghost), (1, self._frequent_ghost)):
            item = segment.pop(key, None)
            if item is not None:
                self._ghost_bytes -= item[0]
                if self._ghost_bytes < 0:
                    self._ghost_bytes = 0
                return kind
        return -1

    def _trim_ghosts(self):
        while (self._ghost_bytes > self._capacity or
               len(self._recent_ghost) + len(self._frequent_ghost) > self._ghost_limit):
            candidate = None
            for kind, segment in ((0, self._recent_ghost), (1, self._frequent_ghost)):
                if segment:
                    key, item = next(iter(segment.items()))
                    serial = item[1]
                    if candidate is None or serial < candidate[0]:
                        candidate = (serial, kind, key, item[0])
            if candidate is None:
                self._ghost_bytes = 0
                break
            _, kind, key, size = candidate
            self._segment_ghost(kind).pop(key, None)
            self._ghost_bytes -= size
            if self._ghost_bytes < 0:
                self._ghost_bytes = 0

    def _segment_ghost(self, kind):
        return self._recent_ghost if kind == 0 else self._frequent_ghost

    def _record_ghost(self, kind, key, size):
        self._take_ghost(key)
        size = max(0, int(size))
        self._ghost_serial += 1
        self._segment_ghost(kind)[key] = (size, self._ghost_serial)
        self._ghost_bytes += size
        self._trim_ghosts()

    def _adjust_target(self, ghost_kind):
        if self._capacity == 0:
            return
        quantum = max(1, self._capacity // 16)
        if ghost_kind == 0:
            self._recent_target = min(self._capacity, self._recent_target + quantum)
        else:
            self._recent_target = max(0, self._recent_target - quantum)

    def _make_room(self, needed, evicted):
        while self._resident_bytes + needed > self._capacity:
            if self._recent and (self._recent_bytes > self._recent_target or not self._frequent):
                kind = 0
            elif self._frequent:
                kind = 1
            elif self._recent:
                kind = 0
            else:
                break
            segment = self._segment(kind)
            key, size = segment.popitem(last=False)
            if kind == 0:
                self._recent_bytes -= size
            else:
                self._frequent_bytes -= size
            self._resident_bytes -= size
            evicted.append(key)
            self._record_ghost(kind, key, size)

    def _insert(self, kind, key, size):
        segment = self._segment(kind)
        segment[key] = size
        if kind == 0:
            self._recent_bytes += size
        else:
            self._frequent_bytes += size
        self._resident_bytes += size

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))
        del now

        if key in self._recent:
            old_size = self._remove_resident(0, key)
            if size > self._capacity:
                self._record_ghost(0, key, old_size)
                return [key]
            evicted = []
            self._make_room(size, evicted)
            self._insert(1, key, size)
            return evicted

        if key in self._frequent:
            old_size = self._remove_resident(1, key)
            if size > self._capacity:
                self._record_ghost(1, key, old_size)
                return [key]
            evicted = []
            self._make_room(size, evicted)
            self._insert(1, key, size)
            return evicted

        ghost_kind = self._take_ghost(key)
        if ghost_kind != -1:
            self._adjust_target(ghost_kind)
            if size > self._capacity:
                return []
            evicted = []
            self._make_room(size, evicted)
            self._insert(1, key, size)
            return evicted

        if size > self._capacity:
            return []

        evicted = []
        self._make_room(size, evicted)
        self._insert(0, key, size)
        return evicted
