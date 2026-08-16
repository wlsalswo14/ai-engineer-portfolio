from collections import OrderedDict

class Policy:
    def __init__(self, capacity_bytes: int):
        try:
            self.capacity = max(0, int(capacity_bytes))
        except Exception:
            self.capacity = 0
        self._items = {}
        self._probation = OrderedDict()
        self._protected = OrderedDict()
        self._total = 0
        self._protected_bytes = 0
        self._protected_target = int(self.capacity * 0.6)
        self._ghost_recent = OrderedDict()
        self._ghost_protected = OrderedDict()
        self._ghost_bytes = 0
        self._ghost_limit_bytes = max(1, self.capacity * 2)
        self._ghost_limit_count = 4096

    def _remove_ghost(self, key):
        value = self._ghost_recent.pop(key, None)
        if value is not None:
            self._ghost_bytes -= value
            return
        value = self._ghost_protected.pop(key, None)
        if value is not None:
            self._ghost_bytes -= value

    def _add_ghost(self, key, size, protected):
        self._remove_ghost(key)
        bucket = self._ghost_protected if protected else self._ghost_recent
        value = max(0, int(size))
        bucket[key] = value
        self._ghost_bytes += value
        while (len(self._ghost_recent) + len(self._ghost_protected) > self._ghost_limit_count or self._ghost_bytes > self._ghost_limit_bytes):
            if self._ghost_recent:
                _, old_size = self._ghost_recent.popitem(last=False)
            elif self._ghost_protected:
                _, old_size = self._ghost_protected.popitem(last=False)
            else:
                break
            self._ghost_bytes -= old_size

    def _adapt(self, key, size):
        delta = max(1, min(self.capacity, max(1, int(size))))
        if key in self._ghost_recent:
            self._remove_ghost(key)
            self._protected_target = min(self.capacity, self._protected_target + delta)
        elif key in self._ghost_protected:
            self._remove_ghost(key)
            self._protected_target = max(0, self._protected_target - delta)

    def _rebalance(self):
        while self._protected_bytes > self._protected_target and self._protected:
            key, _ = self._protected.popitem(last=False)
            node = self._items.get(key)
            if node is None:
                continue
            self._protected_bytes -= node[0]
            node[3] = 0
            self._probation[key] = None

    def _remove_resident(self, key, remember=True):
        node = self._items.pop(key, None)
        if node is None:
            return None
        size, _, _, segment = node
        if segment == 0:
            self._probation.pop(key, None)
        else:
            self._protected.pop(key, None)
            self._protected_bytes -= size
        self._total -= size
        if self._total < 0:
            self._total = 0
        if remember:
            self._add_ghost(key, size, segment == 1)
        return size

    def _pick_victim(self, exclude=None):
        self._rebalance()
        for key in self._probation:
            if key != exclude:
                return key
        for key in self._protected:
            if key != exclude:
                return key
        return None

    def access(self, key: int, size: int, now: int) -> list[int]:
        try:
            requested_size = max(0, int(size))
        except Exception:
            requested_size = 0
        evicted = []

        if self.capacity <= 0:
            for victim in list(self._items):
                self._remove_resident(victim, True)
                evicted.append(victim)
            return evicted

        node = self._items.get(key)
        if node is not None:
            self._total += requested_size - node[0]
            node[0] = requested_size
            node[2] = now
            if requested_size > self.capacity:
                for victim in list(self._items):
                    self._remove_resident(victim, True)
                    evicted.append(victim)
                return evicted
            if node[3] == 0:
                self._probation.pop(key, None)
                self._protected[key] = None
                node[3] = 1
                self._protected_bytes += requested_size
            else:
                self._protected.pop(key, None)
                self._protected[key] = None
                self._protected_bytes += requested_size - (self._items[key][0] if False else 0)
                self._protected_bytes -= requested_size
                self._protected_bytes += requested_size
            node[1] += 1
            self._rebalance()
            while self._total > self.capacity:
                victim = self._pick_victim(exclude=key)
                if victim is None:
                    self._remove_resident(key, True)
                    evicted.append(key)
                    break
                self._remove_resident(victim, True)
                evicted.append(victim)
            return evicted

        if requested_size > self.capacity:
            for victim in list(self._items):
                self._remove_resident(victim, True)
                evicted.append(victim)
            return evicted

        self._adapt(key, requested_size)
        while self._total + requested_size > self.capacity:
            victim = self._pick_victim()
            if victim is None:
                break
            self._remove_resident(victim, True)
            evicted.append(victim)

        if self._total + requested_size <= self.capacity:
            self._items[key] = [requested_size, 1, now, 0]
            self._probation[key] = None
            self._total += requested_size
        return evicted
