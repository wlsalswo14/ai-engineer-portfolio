from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.ghost_limit = 4096
        self.protected_target = self.capacity_bytes // 2
        self.probation_bytes = 0
        self.protected_bytes = 0

    def _drop_ghost(self, key):
        self.ghost_probation.pop(key, None)
        self.ghost_protected.pop(key, None)

    def _remember(self, bucket, key, size):
        self._drop_ghost(key)
        bucket[key] = size
        while len(bucket) > self.ghost_limit:
            bucket.popitem(last=False)

    def _remove_active(self, key):
        if key in self.probation:
            size = self.probation.pop(key)
            self.probation_bytes -= size
            return size, 1
        if key in self.protected:
            size = self.protected.pop(key)
            self.protected_bytes -= size
            return size, 2
        return None, None

    def _rebalance(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size
            self.probation_bytes += size

    def _victim(self):
        probation_limit = self.capacity_bytes - self.protected_target
        if self.probation and (not self.protected or self.probation_bytes > probation_limit):
            key, size = self.probation.popitem(last=False)
            self.probation_bytes -= size
            self._remember(self.ghost_probation, key, size)
            return key
        if self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self._remember(self.ghost_protected, key, size)
            return key
        if self.probation:
            key, size = self.probation.popitem(last=False)
            self.probation_bytes -= size
            self._remember(self.ghost_probation, key, size)
            return key
        return None

    def _make_room(self, size):
        evicted = []
        while self.probation_bytes + self.protected_bytes + size > self.capacity_bytes:
            key = self._victim()
            if key is None:
                break
            evicted.append(key)
        return evicted

    def _adjust_target(self, key, size):
        if key in self.ghost_probation:
            step = max(1, self.capacity_bytes // 16)
            self.protected_target = min(
                self.capacity_bytes,
                self.protected_target + max(step, min(size, self.capacity_bytes)),
            )
            return True
        if key in self.ghost_protected:
            step = max(1, self.capacity_bytes // 16)
            self.protected_target = max(
                0,
                self.protected_target - max(step, min(size, self.capacity_bytes)),
            )
        return False

    def access(self, key: int, size: int, now: int) -> list[int]:
        requested = int(size)

        if requested <= 0:
            if key in self.probation:
                self.probation.move_to_end(key)
            elif key in self.protected:
                self.protected.move_to_end(key)
            return []

        if requested > self.capacity_bytes:
            old_size, segment = self._remove_active(key)
            if segment == 1:
                self._remember(self.ghost_probation, key, old_size)
                return [key]
            if segment == 2:
                self._remember(self.ghost_protected, key, old_size)
                return [key]
            return []

        if key in self.probation:
            self._remove_active(key)
            evicted = self._make_room(requested)
            self.protected[key] = requested
            self.protected_bytes += requested
            self._rebalance()
            return evicted

        if key in self.protected:
            self._remove_active(key)
            evicted = self._make_room(requested)
            self.protected[key] = requested
            self.protected_bytes += requested
            self._rebalance()
            return evicted

        protected_ghost_hit = self._adjust_target(key, requested)
        self._drop_ghost(key)
        evicted = self._make_room(requested)

        if protected_ghost_hit or key in self.ghost_protected:
            self.protected[key] = requested
            self.protected_bytes += requested
            self._rebalance()
        else:
            self.probation[key] = requested
            self.probation_bytes += requested
        return evicted
