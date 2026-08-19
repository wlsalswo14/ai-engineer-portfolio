from collections import OrderedDict

class Policy:
    def __init__(self, capacity_bytes: int):
        self._capacity = capacity_bytes if type(capacity_bytes) is int and capacity_bytes > 0 else 0
        self._probationary = OrderedDict()
        self._protected = OrderedDict()
        self._probationary_bytes = 0
        self._protected_bytes = 0
        self._total = 0
        self._protected_target = max(1, (self._capacity * 7) // 10) if self._capacity else 0
        self._scores = {}
        self._meta_order = OrderedDict()
        self._ghost_limit = 2048
        self._step = 0
        self._last_now = None

    def _resident(self, key):
        return key in self._probationary or key in self._protected

    def _trim_metadata(self):
        limit = len(self._probationary) + len(self._protected) + self._ghost_limit
        while len(self._meta_order) > limit:
            key = next(iter(self._meta_order))
            if self._resident(key):
                self._meta_order.move_to_end(key)
            else:
                self._meta_order.pop(key, None)
                self._scores.pop(key, None)

    def _touch_score(self, key):
        self._scores[key] = min(15, self._scores.get(key, 0) + 1)
        self._meta_order.pop(key, None)
        self._meta_order[key] = None
        self._trim_metadata()

    def _decay(self):
        for key in tuple(self._scores):
            value = self._scores[key] // 2
            if value:
                self._scores[key] = value
            else:
                self._scores.pop(key, None)
                self._meta_order.pop(key, None)

    def _rebalance_protected(self):
        while self._protected_bytes > self._protected_target and len(self._protected) > 1:
            key, value = self._protected.popitem(last=False)
            self._protected_bytes -= value
            self._probationary[key] = value
            self._probationary_bytes += value

    def _remove(self, key, evicted):
        if key in self._probationary:
            value = self._probationary.pop(key)
            self._probationary_bytes -= value
        elif key in self._protected:
            value = self._protected.pop(key)
            self._protected_bytes -= value
        else:
            return
        self._total -= value
        evicted.append(key)

    def _victims(self):
        candidates = []
        for age, (key, value) in enumerate(self._probationary.items()):
            candidates.append((self._scores.get(key, 0), 0, age, key, value))
        for age, (key, value) in enumerate(self._protected.items()):
            candidates.append((self._scores.get(key, 0), 1, age, key, value))
        candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        return candidates

    def _check(self, prior, evicted):
        probationary_keys = list(self._probationary)
        protected_keys = list(self._protected)
        all_keys = probationary_keys + protected_keys
        if len(set(all_keys)) != len(all_keys):
            raise RuntimeError('duplicate resident key')
        if self._probationary_bytes != sum(self._probationary.values()):
            raise RuntimeError('probationary byte accounting error')
        if self._protected_bytes != sum(self._protected.values()):
            raise RuntimeError('protected byte accounting error')
        if self._total != self._probationary_bytes + self._protected_bytes:
            raise RuntimeError('total byte accounting error')
        if self._total < 0 or self._total > self._capacity:
            raise RuntimeError('capacity invariant violated')
        if len(set(evicted)) != len(evicted):
            raise RuntimeError('duplicate eviction')
        current = set(all_keys)
        if any(type(key) is not int or key not in prior or key in current for key in evicted):
            raise RuntimeError('invalid eviction report')

    def _finish(self, prior, evicted):
        self._check(prior, evicted)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        prior = set(self._probationary)
        prior.update(self._protected)
        evicted = []
        self._step += 1
        if self._step % 256 == 0:
            self._decay()
        if type(now) is int:
            self._last_now = now
        if type(key) is not int or type(size) is not int or size <= 0:
            return self._finish(prior, evicted)
        self._touch_score(key)
        if key in self._protected:
            value = self._protected.pop(key)
            self._protected[key] = value
            return self._finish(prior, evicted)
        if key in self._probationary:
            value = self._probationary.pop(key)
            self._probationary_bytes -= value
            self._protected[key] = value
            self._protected_bytes += value
            self._rebalance_protected()
            return self._finish(prior, evicted)
        if self._capacity == 0 or size > self._capacity:
            return self._finish(prior, evicted)
        required = self._total + size - self._capacity
        selected = []
        freed = 0
        if required > 0:
            candidate_score = self._scores.get(key, 0)
            for score, segment, age, victim, victim_size in self._victims():
                if score < candidate_score:
                    selected.append(victim)
                    freed += victim_size
                    if freed >= required:
                        break
            if freed < required:
                return self._finish(prior, evicted)
        for victim in selected:
            self._remove(victim, evicted)
        self._probationary[key] = size
        self._probationary_bytes += size
        self._total += size
        return self._finish(prior, evicted)
