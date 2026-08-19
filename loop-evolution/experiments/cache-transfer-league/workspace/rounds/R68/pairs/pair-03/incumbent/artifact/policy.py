from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.used_bytes = 0
        self.recent_target = self.capacity_bytes // 2
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.entries = {}
        self.ghost_limit = min(4096, max(64, self.capacity_bytes // 64))
        self.resident_limit = max(1, min(8192, self.capacity_bytes))

    def _add_ghost(self, key, segment, size):
        self.b1.pop(key, None)
        self.b2.pop(key, None)
        bucket = self.b1 if segment == 1 else self.b2
        bucket[key] = size
        while len(self.b1) + len(self.b2) > self.ghost_limit:
            if self.b1 and (len(self.b1) >= len(self.b2) or not self.b2):
                self.b1.popitem(last=False)
            elif self.b2:
                self.b2.popitem(last=False)
            else:
                break

    def _remove_ghost(self, key):
        if key in self.b1:
            self.b1.pop(key, None)
            self.b2.pop(key, None)
            return 1
        if key in self.b2:
            self.b2.pop(key, None)
            self.b1.pop(key, None)
            return 2
        return 0

    def _drop_resident(self, key, ghost_segment=0):
        entry = self.entries.pop(key, None)
        if entry is None:
            return
        size, segment = entry[0], entry[1]
        if segment == 1:
            self.t1.pop(key, None)
            self.t1_bytes -= size
        else:
            self.t2.pop(key, None)
            self.t2_bytes -= size
        self.used_bytes -= size
        if ghost_segment:
            self._add_ghost(key, ghost_segment, size)

    def _first_eligible(self, bucket, protected):
        for key in bucket:
            if key != protected:
                return key
        return None

    def _evict_one(self, ghost_hit=0, protected=None):
        t1_bytes = getattr(self, "t1_bytes", 0)
        t2 = self.t2
        choose_t1 = bool(self.t1) and (
            t1_bytes > self.recent_target
            or (ghost_hit == 2 and t1_bytes == self.recent_target)
            or not t2
        )
        if choose_t1:
            primary = (self.t1, 1)
            secondary = (self.t2, 2)
        else:
            primary = (self.t2, 2)
            secondary = (self.t1, 1)
        for bucket, segment in (primary, secondary):
            key = self._first_eligible(bucket, protected)
            if key is not None:
                return key, segment
        return None

    def _make_room(self, required, ghost_hit, protected, evicted, for_insert=False):
        while self.entries and (
            self.used_bytes + required > self.capacity_bytes
            or (for_insert and len(self.entries) >= self.resident_limit)
        ):
            victim = self._evict_one(ghost_hit, protected)
            if victim is None:
                break
            key, segment = victim
            self._drop_resident(key, segment)
            evicted.append(key)

    def _touch(self, key, now):
        entry = self.entries[key]
        entry[2] = now
        entry[3] = min(entry[3] + 1, 1000000000)
        if entry[1] == 1:
            self.t1.pop(key, None)
            self.t1_bytes -= entry[0]
            self.t2[key] = None
            self.t2_bytes += entry[0]
            entry[1] = 2
        else:
            self.t2.move_to_end(key)

    def access(self, key: int, size: int, now: int) -> list[int]:
        size = max(0, int(size))
        evicted = []
        entry = self.entries.get(key)

        if entry is not None:
            old_size = entry[0]
            if size != old_size:
                delta = size - old_size
                entry[0] = size
                self.used_bytes += delta
                if entry[1] == 1:
                    self.t1_bytes += delta
                else:
                    self.t2_bytes += delta
                if size > self.capacity_bytes:
                    segment = entry[1]
                    self._drop_resident(key, segment)
                    evicted.append(key)
                    return evicted
                self._make_room(0, 0, key, evicted)
            self._touch(key, now)
            return evicted

        ghost_hit = self._remove_ghost(key)
        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            return evicted

        step = max(1, min(self.capacity_bytes, size if size else 1))
        if ghost_hit == 1:
            self.recent_target = min(self.capacity_bytes, self.recent_target + step)
        elif ghost_hit == 2:
            self.recent_target = max(0, self.recent_target - step)

        self._make_room(size, ghost_hit, None, evicted, True)
        if self.used_bytes + size > self.capacity_bytes:
            return evicted

        segment = 2 if ghost_hit else 1
        self.entries[key] = [size, segment, now, 2 if ghost_hit else 1]
        if segment == 1:
            self.t1[key] = None
            self.t1_bytes += size
        else:
            self.t2[key] = None
            self.t2_bytes += size
        self.used_bytes += size
        return evicted
