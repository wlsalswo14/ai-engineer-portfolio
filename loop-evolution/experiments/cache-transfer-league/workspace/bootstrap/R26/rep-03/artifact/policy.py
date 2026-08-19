from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probationary = OrderedDict()
        self.protected = OrderedDict()
        self.used_bytes = 0
        self.protected_bytes = 0

    def _rebalance_protected(self):
        target = (self.capacity_bytes * 3) // 4
        while self.protected_bytes > target and self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probationary[key] = size

    def access(self, key: int, size: int, now: int) -> list[int]:
        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.probationary:
            stored_size = self.probationary.pop(key)
            self.probationary[key] = stored_size
            return []

        incoming_size = max(0, int(size))
        if self.capacity_bytes <= 0 or incoming_size > self.capacity_bytes:
            return []

        evicted = []
        while self.used_bytes + incoming_size > self.capacity_bytes:
            if self.probationary:
                old_key, old_size = self.probationary.popitem(last=False)
            elif self.protected:
                old_key, old_size = self.protected.popitem(last=False)
                self.protected_bytes -= old_size
            else:
                break
            self.used_bytes -= old_size
            evicted.append(old_key)

        self.probationary[key] = incoming_size
        self.used_bytes += incoming_size
        return evicted
