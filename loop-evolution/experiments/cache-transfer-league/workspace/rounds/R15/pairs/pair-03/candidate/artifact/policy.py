from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.window_target = max(1, self.capacity_bytes // 8) if self.capacity_bytes else 0
        self.main_target = self.capacity_bytes - self.window_target
        self.protected_target = (self.main_target * 3) // 4
        self.window = OrderedDict()
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.window_bytes = 0
        self.main_bytes = 0
        self.protected_bytes = 0
        self.used_bytes = 0
        self.frequency = {}
        self.requests = 0

    def _record(self, key):
        self.requests += 1
        self.frequency[key] = min(255, self.frequency.get(key, 0) + 1)
        if self.requests % 4096 == 0:
            for stored_key in list(self.frequency):
                value = self.frequency[stored_key] // 2
                if value:
                    self.frequency[stored_key] = value
                else:
                    del self.frequency[stored_key]

    def _remove_window(self, key):
        size = self.window.pop(key)
        self.window_bytes -= size
        self.used_bytes -= size
        return size

    def _remove_main(self, mapping, key):
        size = mapping.pop(key)
        self.main_bytes -= size
        self.used_bytes -= size
        if mapping is self.protected:
            self.protected_bytes -= size
        return size

    def _evict(self, mapping, key, evicted):
        self._remove_window(key) if mapping is self.window else self._remove_main(mapping, key)
        evicted.append(key)

    def _enforce_protected(self, keep):
        while self.protected and self.protected_bytes > self.protected_target:
            key = next((item for item in self.protected if item != keep), None)
            if key is None:
                break
            size = self.protected.pop(key)
            self.protected_bytes -= size
            self.probation[key] = size

    def _enforce_main(self, candidate, keep, evicted):
        while self.main_bytes > self.main_target:
            if candidate is not None and candidate in self.probation:
                victim = next((item for item in self.probation if item != candidate and item != keep), None)
                if victim is not None:
                    if self.frequency.get(candidate, 0) <= self.frequency.get(victim, 0):
                        self._evict(self.probation, candidate, evicted)
                        candidate = None
                    else:
                        self._evict(self.probation, victim, evicted)
                    continue
            victim = next((item for item in self.probation if item != keep), None)
            if victim is not None:
                self._evict(self.probation, victim, evicted)
                continue
            demoted = next((item for item in self.protected if item != keep), None)
            if demoted is not None:
                size = self.protected.pop(demoted)
                self.protected_bytes -= size
                self.probation[demoted] = size
                continue
            if candidate is not None and candidate in self.probation and candidate != keep:
                self._evict(self.probation, candidate, evicted)
                candidate = None
                continue
            break

    def _drain_window(self, keep, evicted):
        while self.window and self.window_bytes > self.window_target:
            key, size = self.window.popitem(last=False)
            self.window_bytes -= size
            self.probation[key] = size
            self.main_bytes += size
            self._enforce_main(key, keep, evicted)

    def _make_room(self, keep, evicted):
        while self.used_bytes > self.capacity_bytes:
            key = next((item for item in self.probation if item != keep), None)
            mapping = self.probation
            if key is None:
                key = next((item for item in self.window if item != keep), None)
                mapping = self.window
            if key is None:
                key = next((item for item in self.protected if item != keep), None)
                mapping = self.protected
            if key is None:
                break
            self._evict(mapping, key, evicted)

    def access(self, key: int, size: int, now: int) -> list[int]:
        size = max(0, int(size))
        self._record(key)
        evicted = []

        if key in self.window:
            old_size = self.window.pop(key)
            self.window_bytes += size - old_size
            self.used_bytes += size - old_size
            self.window[key] = size
            if size > self.capacity_bytes:
                self._remove_window(key)
                evicted.append(key)
                return evicted
            self._drain_window(key, evicted)
            self._make_room(key, evicted)
            return evicted

        if key in self.probation:
            old_size = self.probation.pop(key)
            self.used_bytes += size - old_size
            self.main_bytes += size - old_size
            if size > self.capacity_bytes:
                self.used_bytes -= size
                self.main_bytes -= size
                evicted.append(key)
                return evicted
            self.protected[key] = size
            self.protected_bytes += size
            self._enforce_protected(key)
            self._enforce_main(None, key, evicted)
            self._make_room(key, evicted)
            return evicted

        if key in self.protected:
            old_size = self.protected.pop(key)
            self.used_bytes += size - old_size
            self.main_bytes += size - old_size
            self.protected_bytes += size - old_size
            self.protected[key] = size
            if size > self.capacity_bytes:
                self.protected.pop(key)
                self.used_bytes -= size
                self.main_bytes -= size
                self.protected_bytes -= size
                evicted.append(key)
                return evicted
            self._enforce_protected(key)
            self._enforce_main(None, key, evicted)
            self._make_room(key, evicted)
            return evicted

        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            return evicted

        if size <= self.window_target:
            self.window[key] = size
            self.window_bytes += size
            self.used_bytes += size
            self._drain_window(None, evicted)
        else:
            self.probation[key] = size
            self.main_bytes += size
            self.used_bytes += size
            self._enforce_main(key, None, evicted)

        self._make_room(None, evicted)
        return evicted
