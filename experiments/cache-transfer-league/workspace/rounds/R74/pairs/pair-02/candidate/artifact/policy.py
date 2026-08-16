from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.prob = OrderedDict()
        self.prot = OrderedDict()
        self.ghost_p = OrderedDict()
        self.ghost_q = OrderedDict()
        self.prob_bytes = 0
        self.prot_bytes = 0
        self.ghost_p_bytes = 0
        self.ghost_q_bytes = 0
        self.used = 0
        self.target = (self.capacity * 2) // 3
        self.serial = 0
        self.ghost_serial = 0
        self.ghost_bytes = 0
        self.ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self.ghost_count_limit = 4096

    def _ghost_remove(self, key):
        value = self.ghost_p.pop(key, None)
        if value is not None:
            self.ghost_p_bytes -= value[0]
            self.ghost_bytes -= value[0]
        value = self.ghost_q.pop(key, None)
        if value is not None:
            self.ghost_q_bytes -= value[0]
            self.ghost_bytes -= value[0]

    def _ghost_add(self, key, size, segment):
        self._ghost_remove(key)
        self.ghost_serial += 1
        value = (size, self.ghost_serial)
        table = self.ghost_p if segment == 1 else self.ghost_q
        table[key] = value
        if segment == 1:
            self.ghost_p_bytes += size
        else:
            self.ghost_q_bytes += size
        self.ghost_bytes += size
        while (self.ghost_bytes > self.ghost_limit or
               len(self.ghost_p) + len(self.ghost_q) > self.ghost_count_limit):
            p_stamp = next(iter(self.ghost_p.values()))[1] if self.ghost_p else None
            q_stamp = next(iter(self.ghost_q.values()))[1] if self.ghost_q else None
            if q_stamp is None or (p_stamp is not None and p_stamp < q_stamp):
                _, old = self.ghost_p.popitem(last=False)
                self.ghost_p_bytes -= old[0]
            else:
                _, old = self.ghost_q.popitem(last=False)
                self.ghost_q_bytes -= old[0]
            self.ghost_bytes -= old[0]

    def _adjust_target(self, segment, size):
        if self.capacity <= 0:
            return
        step = max(1, min(self.capacity, max(size, self.capacity // 16)))
        if segment == 1:
            self.target = min(self.capacity, self.target + step)
        else:
            self.target = max(0, self.target - step)

    def _remove_resident(self, key):
        if key in self.prob:
            entry = self.prob.pop(key)
            self.prob_bytes -= entry[0]
            self.used -= entry[0]
            return entry, 1
        if key in self.prot:
            entry = self.prot.pop(key)
            self.prot_bytes -= entry[0]
            self.used -= entry[0]
            return entry, 2
        return None, 0

    def _rebalance(self):
        while self.prot and self.prot_bytes > self.target:
            key, entry = self.prot.popitem(last=False)
            self.prot_bytes -= entry[0]
            self.prob[key] = entry
            self.prob_bytes += entry[0]

    def _evict_one(self):
        self._rebalance()
        if self.prob:
            key, entry = self.prob.popitem(last=False)
            self.prob_bytes -= entry[0]
            self.used -= entry[0]
            self._ghost_add(key, entry[0], 1)
            return key
        if self.prot:
            key, entry = self.prot.popitem(last=False)
            self.prot_bytes -= entry[0]
            self.used -= entry[0]
            self._ghost_add(key, entry[0], 2)
            return key
        return None

    def _make_room(self, incoming):
        evicted = []
        while self.used + incoming > self.capacity:
            key = self._evict_one()
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))
        self.serial += 1

        if key in self.prob or key in self.prot:
            entry, segment = self._remove_resident(key)
            if size <= 0 or size > self.capacity:
                return [key]
            entry[0] = size
            entry[1] = min(255, entry[1] + 1)
            entry[2] = self.serial
            evicted = self._make_room(size)
            if segment == 2 or entry[1] >= 2:
                self.prot[key] = entry
                self.prot_bytes += size
            else:
                self.prob[key] = entry
                self.prob_bytes += size
            self.used += size
            self._rebalance()
            return evicted

        segment = 1 if key in self.ghost_p else 2 if key in self.ghost_q else 0
        if size <= 0 or size > self.capacity:
            return []
        if segment:
            self._adjust_target(segment, size)
            self._ghost_remove(key)

        evicted = self._make_room(size)
        entry = [size, 2 if segment else 1, self.serial]
        if segment:
            self.prot[key] = entry
            self.prot_bytes += size
        else:
            self.prob[key] = entry
            self.prob_bytes += size
        self.used += size
        self._rebalance()
        return evicted
