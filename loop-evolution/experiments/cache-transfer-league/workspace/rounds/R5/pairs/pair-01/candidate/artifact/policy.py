from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.window_limit = 0 if self.capacity_bytes == 0 else max(1, self.capacity_bytes // 8)
        self.entries = {}
        self.window = OrderedDict()
        self.main = OrderedDict()
        self.window_bytes = 0
        self.main_bytes = 0
        self.total_bytes = 0
        self.clock = 0
        self.operations = 0
        self.frequency_a = [0] * 2048
        self.frequency_b = [0] * 2048
        self.max_entries = 4096

    def _indexes(self, key):
        value = int(key)
        mixed = value ^ (value >> 17) ^ (value >> 31)
        return value % 2048, (mixed * 2654435761) % 2048

    def _observe(self, key):
        self.operations += 1
        if self.operations % 64 == 0:
            self.frequency_a = [value // 2 for value in self.frequency_a]
            self.frequency_b = [value // 2 for value in self.frequency_b]
        first, second = self._indexes(key)
        if self.frequency_a[first] < 255:
            self.frequency_a[first] += 1
        if self.frequency_b[second] < 255:
            self.frequency_b[second] += 1

    def _frequency(self, key):
        first, second = self._indexes(key)
        return min(self.frequency_a[first], self.frequency_b[second])

    def _remove(self, key):
        size, segment, _ = self.entries.pop(key)
        if segment == "window":
            self.window.pop(key, None)
            self.window_bytes -= size
        else:
            self.main.pop(key, None)
            self.main_bytes -= size
        self.total_bytes -= size
        return size

    def _report_remove(self, key, requested, evicted, seen):
        self._remove(key)
        if key != requested and key not in seen:
            seen.add(key)
            evicted.append(key)

    def _drop_silently(self, key):
        self._remove(key)

    def _promote(self, key):
        size, segment, last = self.entries[key]
        if segment != "window":
            return
        self.window.pop(key, None)
        self.window_bytes -= size
        self.main[key] = None
        self.main_bytes += size
        self.entries[key] = [size, "main", last]

    def _oldest_window(self, requested):
        for key in self.window:
            if key != requested:
                return key
        return next(iter(self.window), None)

    def _weakest_main(self, excluded=None):
        chosen = None
        chosen_rank = None
        for key, metadata in self.entries.items():
            if metadata[1] != "main" or key == excluded:
                continue
            rank = (self._frequency(key), metadata[2])
            if chosen_rank is None or rank < chosen_rank:
                chosen = key
                chosen_rank = rank
        return chosen

    def _try_promote(self, key, requested, evicted, seen):
        size = self.entries[key][0]
        needed = max(0, self.total_bytes - self.capacity_bytes)
        if needed:
            candidate_frequency = self._frequency(key)
            victims = []
            available = 0
            remaining = list(self.main.keys())
            remaining.sort(key=lambda item: (self._frequency(item), self.entries[item][2]))
            for victim in remaining:
                if self._frequency(victim) >= candidate_frequency:
                    break
                victims.append(victim)
                available += self.entries[victim][0]
                if available >= needed:
                    break
            if available < needed:
                return False
            for victim in victims:
                self._report_remove(victim, requested, evicted, seen)
        self._promote(key)
        return True

    def _enforce_entry_limit(self, requested, evicted, seen):
        while len(self.entries) > self.max_entries:
            victim = self._oldest_window(requested)
            if victim is None:
                victim = self._weakest_main(requested)
            if victim is None:
                if requested in self.entries:
                    self._drop_silently(requested)
                break
            if victim == requested:
                alternate = self._weakest_main(requested)
                if alternate is not None:
                    victim = alternate
                else:
                    self._drop_silently(requested)
                    break
            self._report_remove(victim, requested, evicted, seen)

    def access(self, key: int, size: int, now: int) -> list[int]:
        try:
            requested_size = max(0, int(size))
        except Exception:
            requested_size = 0
        try:
            supplied_time = int(now)
        except Exception:
            supplied_time = self.clock
        self.clock = max(self.clock + 1, supplied_time)
        self._observe(key)

        if key in self.entries:
            metadata = self.entries[key]
            metadata[2] = self.clock
            if metadata[1] == "window":
                self.window.move_to_end(key)
                self._promote(key)
            else:
                self.main.move_to_end(key)
            return []

        if self.capacity_bytes == 0 or requested_size > self.capacity_bytes:
            return []

        self.entries[key] = [requested_size, "window", self.clock]
        self.window[key] = None
        self.window_bytes += requested_size
        self.total_bytes += requested_size
        evicted = []
        seen = set()

        while self.window and (self.window_bytes > self.window_limit or self.total_bytes > self.capacity_bytes):
            candidate = next(iter(self.window))
            candidate_size = self.entries[candidate][0]
            self.window.pop(candidate, None)
            self.window_bytes -= candidate_size
            if self._try_promote(candidate, key, evicted, seen):
                continue
            if candidate == key:
                self._drop_silently(candidate)
            else:
                self._report_remove(candidate, key, evicted, seen)

        if self.total_bytes > self.capacity_bytes:
            while self.total_bytes > self.capacity_bytes:
                victim = self._weakest_main(key)
                if victim is None:
                    victim = self._oldest_window(key)
                if victim is None:
                    break
                self._report_remove(victim, key, evicted, seen)

        self._enforce_entry_limit(key, evicted, seen)
        return evicted
