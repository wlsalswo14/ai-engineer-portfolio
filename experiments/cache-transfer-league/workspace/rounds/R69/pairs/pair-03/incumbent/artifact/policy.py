from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        try:
            capacity = int(capacity_bytes)
        except (TypeError, ValueError, OverflowError):
            capacity = 0
        self.capacity = max(0, capacity)
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.used = 0
        self.recent_target = self.capacity // 2
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.ghost_bytes = 0
        self.ghost_count_limit = 4096
        self.ghost_byte_limit = max(1, self.capacity * 2)
        self.ghost_serial = 0

    @staticmethod
    def _integer(value):
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return 0

    def _drop_ghost(self, key):
        for ghosts in (self.ghost_recent, self.ghost_frequent):
            entry = ghosts.pop(key, None)
            if entry is not None:
                self.ghost_bytes -= entry[0]
        if self.ghost_bytes < 0:
            self.ghost_bytes = 0

    def _remember_ghost(self, key, size, region):
        self._drop_ghost(key)
        self.ghost_serial += 1
        entry = (max(0, size), self.ghost_serial)
        if region == "recent":
            self.ghost_recent[key] = entry
        else:
            self.ghost_frequent[key] = entry
        self.ghost_bytes += entry[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (len(self.ghost_recent) + len(self.ghost_frequent) > self.ghost_count_limit or
               self.ghost_bytes > self.ghost_byte_limit):
            selected = None
            for ghosts in (self.ghost_recent, self.ghost_frequent):
                if ghosts:
                    key = next(iter(ghosts))
                    serial = ghosts[key][1]
                    if selected is None or serial < selected[0]:
                        selected = (serial, ghosts, key)
            if selected is None:
                self.ghost_bytes = 0
                return
            _, ghosts, key = selected
            size, _ = ghosts.pop(key)
            self.ghost_bytes -= size
        if self.ghost_bytes < 0:
            self.ghost_bytes = 0

    def _take_ghost(self, key):
        if key in self.ghost_recent:
            size, _ = self.ghost_recent.pop(key)
            self.ghost_bytes -= size
            return "recent", size
        if key in self.ghost_frequent:
            size, _ = self.ghost_frequent.pop(key)
            self.ghost_bytes -= size
            return "frequent", size
        return None, 0

    def _adjust_target(self, region, evidence_size):
        if self.capacity <= 0:
            self.recent_target = 0
            return
        step = max(1, min(self.capacity, max(0, evidence_size)))
        if region == "recent":
            self.recent_target = min(self.capacity, self.recent_target + step)
        else:
            self.recent_target = max(0, self.recent_target - step)

    def _remove_resident(self, key):
        if key in self.recent:
            size = self.recent.pop(key)
            self.recent_bytes -= size
            self.used -= size
            return "recent", size
        if key in self.frequent:
            size = self.frequent.pop(key)
            self.frequent_bytes -= size
            self.used -= size
            return "frequent", size
        return None

    def _insert(self, key, size, region):
        if region == "recent":
            self.recent[key] = size
            self.recent_bytes += size
        else:
            self.frequent[key] = size
            self.frequent_bytes += size
        self.used += size

    def _make_room(self, incoming, evicted):
        while self.used + incoming > self.capacity:
            if self.recent and (self.recent_bytes > self.recent_target or not self.frequent):
                key, size = self.recent.popitem(last=False)
                region = "recent"
                self.recent_bytes -= size
            elif self.frequent:
                key, size = self.frequent.popitem(last=False)
                region = "frequent"
                self.frequent_bytes -= size
            elif self.recent:
                key, size = self.recent.popitem(last=False)
                region = "recent"
                self.recent_bytes -= size
            else:
                break
            self.used -= size
            self._remember_ghost(key, size, region)
            if key not in evicted:
                evicted.append(key)

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = self._integer(key)
        size = max(0, self._integer(size))
        evicted = []

        resident = self._remove_resident(key)
        if resident is not None:
            self._drop_ghost(key)
            if size > self.capacity:
                return [key]
            self._make_room(size, evicted)
            self._insert(key, size, "frequent")
            return evicted

        if size > self.capacity:
            self._drop_ghost(key)
            return evicted

        ghost_region, ghost_size = self._take_ghost(key)
        if ghost_region is not None:
            self._adjust_target(ghost_region, ghost_size)
            self._make_room(size, evicted)
            self._insert(key, size, "frequent")
        else:
            self._make_room(size, evicted)
            self._insert(key, size, "recent")
        return evicted
