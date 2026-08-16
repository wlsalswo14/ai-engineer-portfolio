from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        capacity = int(capacity_bytes)
        self.capacity_bytes = capacity if capacity > 0 else 0
        self.probationary = OrderedDict()
        self.protected = OrderedDict()
        self.used_bytes = 0
        self.probationary_bytes = 0
        self.protected_bytes = 0
        self.request_count = 0
        self.hit_count = 0
        self.miss_count = 0
        self.repeat_count = 0
        self.eviction_count = 0
        self.last_key = None
        self.last_evictions = ()
        self._adapt_interval = 64
        self._protected_target = (self.capacity_bytes * 3) // 4
        self._recent_protected_hits = 0
        self._recent_probationary_hits = 0
        self._recent_promotions = 0
        self._recent_misses = 0

    def _remove_probationary(self, key):
        stored_size = self.probationary.pop(key)
        self.probationary_bytes -= stored_size
        self.used_bytes -= stored_size
        return stored_size

    def _remove_protected(self, key):
        stored_size = self.protected.pop(key)
        self.protected_bytes -= stored_size
        self.used_bytes -= stored_size
        return stored_size

    def _promote(self, key):
        stored_size = self._remove_probationary(key)
        self.protected[key] = stored_size
        self.protected_bytes += stored_size
        self.used_bytes += stored_size

    def _demote_oldest_protected(self):
        if not self.protected:
            return None
        key, stored_size = self.protected.popitem(last=False)
        self.protected_bytes -= stored_size
        self.probationary[key] = stored_size
        self.probationary_bytes += stored_size
        return key

    def _enforce_protected_target(self):
        while self.protected_bytes > self._protected_target and len(self.protected) > 1:
            self._demote_oldest_protected()

    def _evict_one(self):
        if self.probationary:
            key, stored_size = self.probationary.popitem(last=False)
            self.probationary_bytes -= stored_size
            self.used_bytes -= stored_size
            return key
        if self.protected:
            key, stored_size = self.protected.popitem(last=False)
            self.protected_bytes -= stored_size
            self.used_bytes -= stored_size
            return key
        return None

    def _state_ok(self):
        if set(self.probationary).intersection(self.protected):
            return False
        if self.probationary_bytes != sum(self.probationary.values()):
            return False
        if self.protected_bytes != sum(self.protected.values()):
            return False
        if self.used_bytes != self.probationary_bytes + self.protected_bytes:
            return False
        return self.used_bytes <= self.capacity_bytes

    def _repair_state(self):
        self.probationary_bytes = sum(self.probationary.values())
        self.protected_bytes = sum(self.protected.values())
        self.used_bytes = self.probationary_bytes + self.protected_bytes

    def _adapt(self):
        reuse_pressure = self._recent_probationary_hits + self._recent_promotions
        if reuse_pressure > self._recent_protected_hits:
            step = max(1, self.capacity_bytes // 16)
            self._protected_target = min(self.capacity_bytes, self._protected_target + step)
        elif (self._recent_misses >= (self._adapt_interval * 3) // 4 and
              self._recent_promotions == 0 and
              self._recent_protected_hits == 0):
            step = max(1, self.capacity_bytes // 16)
            self._protected_target = max(0, self._protected_target - step)
        self._recent_protected_hits = 0
        self._recent_probationary_hits = 0
        self._recent_promotions = 0
        self._recent_misses = 0
        self._enforce_protected_target()

    def _finish(self, evicted):
        if self.request_count % self._adapt_interval == 0:
            self._adapt()
            if not self._state_ok():
                self._repair_state()
                while self.used_bytes > self.capacity_bytes:
                    victim = self._evict_one()
                    if victim is None:
                        break
                    evicted.append(victim)
        self.eviction_count += len(evicted)
        self.last_evictions = tuple(evicted)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        self.request_count += 1
        if key == self.last_key:
            self.repeat_count += 1
        self.last_key = key

        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            self.hit_count += 1
            self._recent_protected_hits += 1
            return self._finish([])

        if key in self.probationary:
            self._promote(key)
            self.hit_count += 1
            self._recent_probationary_hits += 1
            self._recent_promotions += 1
            self._enforce_protected_target()
            return self._finish([])

        self.miss_count += 1
        self._recent_misses += 1
        incoming_size = int(size)
        if incoming_size < 0:
            incoming_size = 0
        if incoming_size > self.capacity_bytes:
            return self._finish([])

        self._enforce_protected_target()
        evicted = []
        while self.used_bytes + incoming_size > self.capacity_bytes:
            victim = self._evict_one()
            if victim is None:
                break
            evicted.append(victim)

        self.probationary[key] = incoming_size
        self.probationary_bytes += incoming_size
        self.used_bytes += incoming_size
        return self._finish(evicted)
