from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.sizes = {}
        self.segments = {}
        self.used_bytes = 0
        self.protected_bytes = 0
        self.protected_budget = (self.capacity_bytes * 3) // 5
        if self.capacity_bytes and self.protected_budget == 0:
            self.protected_budget = 1
        self.adjustment = max(1, self.capacity_bytes // 8)
        self.ghost = OrderedDict()
        self.ghost_limit = 4096

    def _remember_ghost(self, key, size, segment):
        self.ghost.pop(key, None)
        self.ghost[key] = (size, segment)
        while len(self.ghost) > self.ghost_limit:
            self.ghost.popitem(last=False)

    def _adapt_budget(self, segment):
        if not self.capacity_bytes:
            return
        minimum = max(1, self.capacity_bytes // 8)
        if segment == "probation":
            self.protected_budget = max(
                minimum, self.protected_budget - self.adjustment
            )
        else:
            self.protected_budget = min(
                self.capacity_bytes, self.protected_budget + self.adjustment
            )

    def _rebalance(self):
        while (
            len(self.protected) > 1
            and self.protected_bytes > self.protected_budget
        ):
            key, _ = self.protected.popitem(last=False)
            size = self.sizes[key]
            self.protected_bytes -= size
            self.probation[key] = None
            self.segments[key] = "probation"

    def _evict_one(self, segment):
        container = self.probation if segment == "probation" else self.protected
        key, _ = container.popitem(last=False)
        size = self.sizes.pop(key)
        self.segments.pop(key, None)
        self.used_bytes -= size
        if segment == "protected":
            self.protected_bytes -= size
        self._remember_ghost(key, size, segment)
        return key

    def _make_room(self, incoming_size):
        evicted = []
        while self.used_bytes + incoming_size > self.capacity_bytes:
            if self.probation:
                evicted.append(self._evict_one("probation"))
            elif self.protected:
                evicted.append(self._evict_one("protected"))
            else:
                break
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size = self.sizes[key]
            self.protected.pop(key)
            self.protected[key] = None
            return []

        if key in self.probation:
            stored_size = self.sizes[key]
            self.probation.pop(key)
            self.protected[key] = None
            self.segments[key] = "protected"
            self.protected_bytes += stored_size
            self._rebalance()
            return []

        request_size = max(0, size)
        if self.capacity_bytes == 0 or request_size > self.capacity_bytes:
            return []

        ghost_record = self.ghost.pop(key, None)
        promoted = ghost_record is not None
        if promoted:
            self._adapt_budget(ghost_record[1])

        self._rebalance()
        if promoted:
            self.protected[key] = None
            self.segments[key] = "protected"
            self.protected_bytes += request_size
        else:
            self.probation[key] = None
            self.segments[key] = "probation"
        self.sizes[key] = request_size
        self.used_bytes += request_size

        if promoted:
            self._rebalance()
        return self._make_room(request_size=0) if False else self._make_room(0)
