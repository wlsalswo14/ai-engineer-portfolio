from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.t1_bytes = 0
        self.t2_bytes = 0
        self.b1_bytes = 0
        self.b2_bytes = 0
        self.used = 0
        self.target = self.capacity // 2
        self.serial = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096

    def _drop_ghost(self, key):
        value = self.b1.pop(key, None)
        if value is not None:
            self.b1_bytes -= value[0]
        value = self.b2.pop(key, None)
        if value is not None:
            self.b2_bytes -= value[0]

    def _remember(self, key, size, frequent):
        self._drop_ghost(key)
        self.serial += 1
        value = (size, self.serial)
        if frequent:
            self.b2[key] = value
            self.b2_bytes += size
        else:
            self.b1[key] = value
            self.b1_bytes += size
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.b1_bytes + self.b2_bytes > self.ghost_limit or
               len(self.b1) + len(self.b2) > self.ghost_count_limit):
            first_kind = 0
            first_serial = None
            if self.b1:
                key = next(iter(self.b1))
                first_kind = 1
                first_serial = self.b1[key][1]
            if self.b2:
                key = next(iter(self.b2))
                candidate_serial = self.b2[key][1]
                if first_serial is None or candidate_serial < first_serial:
                    first_kind = 2
                    first_serial = candidate_serial
            if first_kind == 1:
                _, value = self.b1.popitem(last=False)
                self.b1_bytes -= value[0]
            elif first_kind == 2:
                _, value = self.b2.popitem(last=False)
                self.b2_bytes -= value[0]
            else:
                break

    def _adjust_target(self, frequent_ghost):
        if self.capacity <= 0:
            return
        if frequent_ghost:
            if self.b2_bytes == 0:
                delta = self.capacity
            else:
                delta = max(1, min(self.capacity, self.b1_bytes // self.b2_bytes))
            self.target = max(0, self.target - delta)
        else:
            if self.b1_bytes == 0:
                delta = self.capacity
            else:
                delta = max(1, min(self.capacity, self.b2_bytes // self.b1_bytes))
            self.target = min(self.capacity, self.target + delta)

    def _remove_resident(self, key):
        if key in self.t1:
            size = self.t1.pop(key)
            self.t1_bytes -= size
            self.used -= size
            return size, False
        if key in self.t2:
            size = self.t2.pop(key)
            self.t2_bytes -= size
            self.used -= size
            return size, True
        return 0, False

    def _evict_one(self, frequent_ghost):
        take_t1 = bool(self.t1) and (
            self.t1_bytes > self.target or
            (frequent_ghost and self.t1_bytes == self.target)
        )
        if take_t1 or not self.t2:
            if self.t1:
                key, size = self.t1.popitem(last=False)
                self.t1_bytes -= size
                self.used -= size
                self._remember(key, size, False)
                return key
        if self.t2:
            key, size = self.t2.popitem(last=False)
            self.t2_bytes -= size
            self.used -= size
            self._remember(key, size, True)
            return key
        if self.t1:
            key, size = self.t1.popitem(last=False)
            self.t1_bytes -= size
            self.used -= size
            self._remember(key, size, False)
            return key
        return None

    def _make_room(self, incoming, frequent_ghost):
        evicted = []
        while self.used + incoming > self.capacity:
            key = self._evict_one(frequent_ghost)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))

        if key in self.t1 or key in self.t2:
            self._remove_resident(key)
            if size > self.capacity:
                self._drop_ghost(key)
                return [key]
            evicted = self._make_room(size, False)
            self._drop_ghost(key)
            self.t2[key] = size
            self.t2_bytes += size
            self.used += size
            return evicted

        frequent_ghost = key in self.b2
        recent_ghost = key in self.b1
        if size > self.capacity:
            self._drop_ghost(key)
            return []

        if frequent_ghost or recent_ghost:
            self._adjust_target(frequent_ghost)
            self._drop_ghost(key)
            evicted = self._make_room(size, frequent_ghost)
            self.t2[key] = size
            self.t2_bytes += size
        else:
            evicted = self._make_room(size, False)
            self.t1[key] = size
            self.t1_bytes += size
        self.used += size
        return evicted
