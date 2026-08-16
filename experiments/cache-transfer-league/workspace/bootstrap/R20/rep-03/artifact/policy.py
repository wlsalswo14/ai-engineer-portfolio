from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = capacity_bytes
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.ghosts = OrderedDict()
        self.used_bytes = 0

    def _remember(self, key):
        self.ghosts.pop(key, None)
        self.ghosts[key] = None

    def _trim_ghosts(self):
        limit = max(1, len(self.probation) + len(self.protected))
        while len(self.ghosts) > limit:
            self.ghosts.popitem(last=False)

    def _make_room(self, size, evicted):
        while self.used_bytes + size > self.capacity_bytes:
            if self.probation:
                key, stored_size = self.probation.popitem(last=False)
                self.used_bytes -= stored_size
                self._remember(key)
                evicted.append(key)
            elif self.protected:
                key, stored_size = self.protected.popitem(last=False)
                self.probation[key] = stored_size
            else:
                break

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if size > self.capacity_bytes:
            return []

        promoted = key in self.ghosts
        self.ghosts.pop(key, None)
        evicted = []
        self._make_room(size, evicted)

        if promoted:
            self.protected[key] = size
        else:
            self.probation[key] = size
        self.used_bytes += size
        self._trim_ghosts()
        return evicted
