from collections import OrderedDict

class Policy:
    def __init__(self, capacity_bytes):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self._recent_limit = max(1, self.capacity_bytes // 5) if self.capacity_bytes else 0
        self._used = 0
        self._recent_bytes = 0
        self._protected_bytes = 0
        self._recent = OrderedDict()
        self._protected = OrderedDict()
        self._sizes = {}
        self._scores = {}
        self._history = OrderedDict()
        self._history_limit = 4096
        self._step = 0

    def _remember_score(self, key, score):
        self._history.pop(key, None)
        self._history[key] = max(1, int(score))
        while len(self._history) > self._history_limit:
            self._history.popitem(last=False)

    def _remove(self, key, output):
        size = self._sizes.pop(key, 0)
        score = self._scores.pop(key, 1)
        if key in self._recent:
            self._recent.pop(key, None)
            self._recent_bytes -= size
        elif key in self._protected:
            self._protected.pop(key, None)
            self._protected_bytes -= size
        self._used -= size
        self._recent_bytes = max(0, self._recent_bytes)
        self._protected_bytes = max(0, self._protected_bytes)
        self._used = max(0, self._used)
        self._remember_score(key, score)
        if isinstance(key, int) and not isinstance(key, bool):
            output.append(key)

    def _oldest(self, group, excluded):
        for key in group:
            if key != excluded:
                return key
        return None

    def _protected_budget(self):
        base = max(0, self.capacity_bytes - self._recent_limit)
        largest = 0
        for key in self._protected:
            largest = max(largest, self._sizes.get(key, 0))
        return max(base, largest)

    def _protected_victim(self):
        victim = None
        victim_score = None
        for key in self._protected:
            score = self._scores.get(key, 1)
            if victim is None or score < victim_score:
                victim = key
                victim_score = score
        return victim

    def _decay(self):
        if self._step % 256:
            return
        for key in list(self._scores):
            self._scores[key] = max(1, self._scores[key] // 2)
        for key in list(self._history):
            self._history[key] = max(1, self._history[key] // 2)

    def _rebalance(self, sticky=None):
        output = []
        while self._used > self.capacity_bytes:
            victim = self._oldest(self._recent, sticky)
            if victim is None:
                victim = self._protected_victim()
            if victim is None:
                break
            self._remove(victim, output)

        while self._protected_bytes > self._protected_budget():
            victim = self._protected_victim()
            if victim is None:
                break
            size = self._sizes[victim]
            self._protected.pop(victim, None)
            self._protected_bytes -= size
            self._recent[victim] = None
            self._recent_bytes += size

        while self._recent_bytes > self._recent_limit:
            victim = self._oldest(self._recent, sticky)
            if victim is None:
                break
            self._remove(victim, output)

        while self._used > self.capacity_bytes:
            victim = self._oldest(self._recent, sticky)
            if victim is None:
                victim = self._protected_victim()
            if victim is None:
                break
            self._remove(victim, output)
        return output

    def access(self, key, size, now):
        del now
        if not isinstance(key, int) or isinstance(key, bool):
            return []
        size = max(0, int(size))
        self._step += 1
        self._decay()

        if key in self._sizes:
            old_size = self._sizes[key]
            if old_size != size:
                delta = size - old_size
                self._sizes[key] = size
                self._used += delta
                if key in self._recent:
                    self._recent_bytes += delta
                else:
                    self._protected_bytes += delta
            self._scores[key] = self._scores.get(key, 1) + 1
            if key in self._recent:
                self._recent.pop(key, None)
                self._recent_bytes -= size
                self._protected[key] = None
                self._protected_bytes += size
            else:
                self._protected.move_to_end(key)
            return self._rebalance(sticky=key)

        if self.capacity_bytes <= 0 or size > self.capacity_bytes:
            output = []
            for victim in list(self._sizes):
                self._remove(victim, output)
            return output

        prior = self._history.pop(key, 0)
        self._scores[key] = max(1, prior + 1)
        self._sizes[key] = size
        self._recent[key] = None
        self._recent_bytes += size
        self._used += size
        return self._rebalance(sticky=key)
