from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        try:
            capacity = int(capacity_bytes)
        except (TypeError, ValueError):
            capacity = 0
        self.capacity = max(0, capacity)
        self._entries = {}
        self._probationary = OrderedDict()
        self._protected = OrderedDict()
        self._recent_ghost = OrderedDict()
        self._frequent_ghost = OrderedDict()
        self._used = 0
        self._protected_bytes = 0
        self._protected_target = self.capacity // 2
        self._clock = 0
        self._history_limit = max(64, min(4096, self.capacity + 64))

    def _key_is_legal(self, key):
        return isinstance(key, int) and not isinstance(key, bool)

    def _normal_size(self, size):
        try:
            value = int(size)
        except (TypeError, ValueError):
            value = 0
        return max(0, value)

    def _remember_ghost(self, key, size, frequent):
        recent = self._recent_ghost
        frequent_map = self._frequent_ghost
        recent.pop(key, None)
        frequent_map.pop(key, None)
        target = frequent_map if frequent else recent
        target[key] = size
        while len(target) > self._history_limit:
            target.popitem(last=False)

    def _remove_entry(self, key):
        entry = self._entries.pop(key)
        size = entry["size"]
        self._used -= size
        if entry["segment"] == 1:
            self._protected.pop(key, None)
            self._protected_bytes -= size
            self._remember_ghost(key, size, True)
        else:
            self._probationary.pop(key, None)
            self._remember_ghost(key, size, False)
        return key

    def _effective_frequency(self, entry):
        age = max(0, self._clock - entry["last"])
        decay = min(8, age // 32)
        return max(1, entry["frequency"] >> decay)

    def _trim_protected(self):
        while len(self._protected) > 1 and self._protected_bytes > self._protected_target:
            key = next(iter(self._protected))
            entry = self._entries[key]
            self._protected.pop(key, None)
            self._protected_bytes -= entry["size"]
            entry["segment"] = 0
            self._probationary[key] = None

    def _victims_for(self, required, excluded):
        victims = []
        freed = 0
        for key in list(self._probationary):
            if key == excluded:
                continue
            entry = self._entries.get(key)
            if entry is None:
                continue
            victims.append(self._remove_entry(key))
            freed += entry["size"]
            if freed >= required:
                return victims
        protected_keys = [
            key for key in self._protected
            if key != excluded and key in self._entries
        ]
        protected_keys.sort(
            key=lambda candidate: (
                self._effective_frequency(self._entries[candidate]),
                self._entries[candidate]["last"],
                candidate,
            )
        )
        for key in protected_keys:
            entry = self._entries.get(key)
            if entry is None:
                continue
            victims.append(self._remove_entry(key))
            freed += entry["size"]
            if freed >= required:
                break
        return victims

    def _add_entry(self, key, size, protected, frequency):
        entry = {
            "size": size,
            "segment": 1 if protected else 0,
            "frequency": max(1, frequency),
            "last": self._clock,
        }
        self._entries[key] = entry
        self._used += size
        if protected:
            self._protected[key] = None
            self._protected_bytes += size
        else:
            self._probationary[key] = None

    def access(self, key, size, now):
        self._clock += 1
        if not self._key_is_legal(key):
            return []
        size = self._normal_size(size)
        victims = []

        if key in self._entries:
            entry = self._entries[key]
            if size > self.capacity:
                for candidate in list(self._entries):
                    victims.append(self._remove_entry(candidate))
                return victims

            delta = size - entry["size"]
            if delta > 0 and self._used + delta > self.capacity:
                victims.extend(
                    self._victims_for(self._used + delta - self.capacity, key)
                )
            entry = self._entries.get(key)
            if entry is None:
                return victims
            if delta:
                self._used += delta
                if entry["segment"] == 1:
                    self._protected_bytes += delta
                entry["size"] = size
            entry["frequency"] = min(1 << 20, entry["frequency"] + 1)
            entry["last"] = self._clock
            if entry["segment"] == 0:
                self._probationary.pop(key, None)
                entry["segment"] = 1
                self._protected[key] = None
                self._protected_bytes += entry["size"]
            else:
                self._protected.pop(key, None)
                self._protected[key] = None
            self._trim_protected()
            return victims

        frequent_reentry = key in self._frequent_ghost
        recent_reentry = key in self._recent_ghost
        if frequent_reentry:
            self._frequent_ghost.pop(key, None)
            step = max(1, max(size, self.capacity // 16))
            self._protected_target = min(self.capacity, self._protected_target + step)
        elif recent_reentry:
            self._recent_ghost.pop(key, None)
            step = max(1, max(size, self.capacity // 16))
            self._protected_target = max(0, self._protected_target - step)

        if size > self.capacity:
            for candidate in list(self._entries):
                victims.append(self._remove_entry(candidate))
            return victims

        required = max(0, self._used + size - self.capacity)
        if required:
            victims.extend(self._victims_for(required, None))

        if self._used + size <= self.capacity:
            self._add_entry(
                key,
                size,
                frequent_reentry,
                2 if frequent_reentry else 1,
            )
            self._trim_protected()
        return victims
