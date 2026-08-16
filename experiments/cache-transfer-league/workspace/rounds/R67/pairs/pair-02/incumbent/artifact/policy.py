from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.total = 0
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.ghost_limit = 1024
        self.tick = 0

    def _timestamp(self, now):
        try:
            value = int(now)
        except (TypeError, ValueError):
            value = self.tick + 1
        if value <= self.tick:
            value = self.tick + 1
        self.tick = value
        return value

    def _remember(self, ghost, key, size):
        ghost.pop(key, None)
        ghost[key] = size
        while len(ghost) > self.ghost_limit:
            ghost.popitem(last=False)

    def _drop(self, key, remember=True):
        if key in self.recent:
            item = self.recent.pop(key)
            segment = self.ghost_recent
        elif key in self.frequent:
            item = self.frequent.pop(key)
            segment = self.ghost_frequent
        else:
            return None
        self.total -= item[0]
        if self.total < 0:
            self.total = 0
        if remember:
            self._remember(segment, key, item[0])
        return item

    def _victim(self, protected=None):
        candidate = None
        candidate_score = None
        for key, item in self.recent.items():
            if key == protected:
                continue
            score = (0, item[1], item[2], -item[0], key)
            if candidate_score is None or score < candidate_score:
                candidate = key
                candidate_score = score
        for key, item in self.frequent.items():
            if key == protected:
                continue
            score = (1, item[1], item[2], -item[0], key)
            if candidate_score is None or score < candidate_score:
                candidate = key
                candidate_score = score
        return candidate

    def _evict_until_fit(self, required, protected=None):
        evicted = []
        seen = set()
        while self.total + required > self.capacity:
            victim = self._victim(protected)
            if victim is None:
                break
            self._drop(victim, remember=True)
            if isinstance(victim, int) and victim not in seen:
                seen.add(victim)
                evicted.append(victim)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        stamp = self._timestamp(now)
        try:
            requested = int(size)
        except (TypeError, ValueError):
            requested = 0
        requested = max(0, requested)

        if key in self.recent:
            if requested > self.capacity:
                self._drop(key, remember=True)
                return [key] if isinstance(key, int) else []
            item = self.recent.pop(key)
            self.total += requested - item[0]
            item[0] = requested
            item[1] += 1
            item[2] = stamp
            self.frequent[key] = item
            return self._evict_until_fit(0, protected=key)

        if key in self.frequent:
            if requested > self.capacity:
                self._drop(key, remember=True)
                return [key] if isinstance(key, int) else []
            item = self.frequent.pop(key)
            self.total += requested - item[0]
            item[0] = requested
            item[1] += 1
            item[2] = stamp
            self.frequent[key] = item
            return self._evict_until_fit(0, protected=key)

        if self.capacity <= 0 or requested > self.capacity:
            return []

        ghost_frequent_hit = key in self.ghost_frequent
        ghost_recent_hit = key in self.ghost_recent
        self.ghost_frequent.pop(key, None)
        self.ghost_recent.pop(key, None)

        evicted = self._evict_until_fit(requested)
        item = [requested, 1, stamp]
        if ghost_frequent_hit or ghost_recent_hit:
            self.frequent[key] = item
        else:
            self.recent[key] = item
        self.total += requested
        return evicted
