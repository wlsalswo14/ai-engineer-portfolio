from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghost = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0
        self.protected_target = self.capacity_bytes // 2
        self.ghost_limit = 4096

    def _remember(self, key, segment):
        self.ghost.pop(key, None)
        self.ghost[key] = segment
        while len(self.ghost) > self.ghost_limit:
            self.ghost.popitem(last=False)

    def _rebalance_protected(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size

    def _adapt_from_ghost(self, key, size):
        segment = self.ghost.pop(key, None)
        if segment is None:
            return False
        step = max(1, min(size, self.capacity_bytes))
        if segment == 'protected':
            self.protected_target = min(
                self.capacity_bytes, self.protected_target + step
            )
        else:
            self.protected_target = max(0, self.protected_target - step)
        return True

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            self._rebalance_protected()
            return []

        if self.capacity_bytes == 0 or size <= 0 or size > self.capacity_bytes:
            return []

        admitted_protected = self._adapt_from_ghost(key, size)
        self._rebalance_protected()
        evicted = []

        while self.used_bytes + size > self.capacity_bytes:
            if self.probation:
                old_key, old_size = self.probation.popitem(last=False)
                self._remember(old_key, 'probation')
            elif self.protected:
                old_key, old_size = self.protected.popitem(last=False)
                self.protected_bytes -= old_size
                self._remember(old_key, 'protected')
            else:
                break
            self.used_bytes -= old_size
            evicted.append(old_key)

        if admitted_protected:
            self.protected[key] = size
            self.protected_bytes += size
        else:
            self.probation[key] = size
        self.used_bytes += size
        self._rebalance_protected()
        return evicted
