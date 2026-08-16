from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
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
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096
        self.serial = 0
        self.ghost_order = {}

    def _remove_ghost(self, key):
        value = self.b1.pop(key, None)
        if value is not None:
            self.b1_bytes -= value
            self.ghost_order.pop(key, None)
            return 1
        value = self.b2.pop(key, None)
        if value is not None:
            self.b2_bytes -= value
            self.ghost_order.pop(key, None)
            return 2
        return 0

    def _remember_ghost(self, key, size, kind):
        self._remove_ghost(key)
        value = max(0, int(size))
        self.serial += 1
        self.ghost_order[key] = self.serial
        if kind == 1:
            self.b1[key] = value
            self.b1_bytes += value
        else:
            self.b2[key] = value
            self.b2_bytes += value
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self.b1_bytes + self.b2_bytes > self.ghost_limit or
               len(self.b1) + len(self.b2) > self.ghost_count_limit):
            key = None
            stamp = None
            for ghosts in (self.b1, self.b2):
                if ghosts:
                    candidate = next(iter(ghosts))
                    candidate_stamp = self.ghost_order[candidate]
                    if stamp is None or candidate_stamp < stamp:
                        key = candidate
                        stamp = candidate_stamp
            if key is None:
                break
            self._remove_ghost(key)

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        if kind == 1:
            if self.b1_bytes == 0:
                step = self.capacity
            else:
                step = max(1, self.b2_bytes // self.b1_bytes)
            self.target = min(self.capacity, self.target + min(self.capacity, step))
        else:
            if self.b2_bytes == 0:
                step = self.capacity
            else:
                step = max(1, self.b1_bytes // self.b2_bytes)
            self.target = max(0, self.target - min(self.capacity, step))

    def _remove_resident(self, key):
        value = self.t1.pop(key, None)
        if value is not None:
            self.t1_bytes -= value
            self.used -= value
            return value, 1
        value = self.t2.pop(key, None)
        if value is not None:
            self.t2_bytes -= value
            self.used -= value
            return value, 2
        return None, 0

    def _evict_one(self, choose_t1):
        if choose_t1 and self.t1:
            key, value = self.t1.popitem(last=False)
            self.t1_bytes -= value
            self.used -= value
            self._remember_ghost(key, value, 1)
            return key
        if self.t2:
            key, value = self.t2.popitem(last=False)
            self.t2_bytes -= value
            self.used -= value
            self._remember_ghost(key, value, 2)
            return key
        if self.t1:
            key, value = self.t1.popitem(last=False)
            self.t1_bytes -= value
            self.used -= value
            self._remember_ghost(key, value, 1)
            return key
        return None

    def _make_room(self, incoming, ghost_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            if ghost_kind == 1:
                choose_t1 = self.t1_bytes >= self.target
            elif ghost_kind == 2:
                choose_t1 = self.t1_bytes > self.target
            else:
                choose_t1 = self.t1_bytes > self.target
            key = self._evict_one(choose_t1)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key, size, now):
        key = int(key)
        size = max(0, int(size))

        old_size, old_kind = self._remove_resident(key)
        if old_kind:
            if size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            if self.used + size > self.capacity:
                return evicted + [key]
            self._remove_ghost(key)
            self.t2[key] = size
            self.t2_bytes += size
            self.used += size
            return evicted

        ghost_kind = 1 if key in self.b1 else 2 if key in self.b2 else 0
        if size > self.capacity:
            return []
        if ghost_kind:
            self._adjust_target(ghost_kind)
            self._remove_ghost(key)

        evicted = self._make_room(size, ghost_kind)
        if self.used + size > self.capacity:
            return evicted

        if ghost_kind:
            self.t2[key] = size
            self.t2_bytes += size
        else:
            self.t1[key] = size
            self.t1_bytes += size
        self.used += size
        return evicted
