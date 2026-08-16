from math import isqrt


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self._entries = {}
        self._history = {}
        self._used = 0
        self._steps = 0
        self._epoch = 0
        self._history_limit = 8192

    def _advance(self):
        self._steps += 1
        self._epoch = self._steps >> 8

    def _current(self, count, stamp):
        shift = self._epoch - stamp
        if shift <= 0:
            return count
        if shift >= count.bit_length():
            return 0
        return count >> shift

    def _trim_history(self, keep):
        while len(self._history) > self._history_limit:
            candidates = ((k, v) for k, v in self._history.items() if k != keep)
            victim = min(
                candidates,
                key=lambda item: (self._current(item[1][0], item[1][1]), item[0]),
                default=None,
            )
            if victim is None:
                break
            del self._history[victim[0]]

    def _observe_miss(self, key):
        record = self._history.get(key)
        count = 0 if record is None else self._current(record[0], record[1])
        count += 1
        self._history[key] = [count, self._epoch]
        self._trim_history(key)
        return count

    def _remember(self, key, count):
        record = self._history.get(key)
        old = 0 if record is None else self._current(record[0], record[1])
        self._history[key] = [max(old, count), self._epoch]
        self._trim_history(key)

    def _entry_count(self, entry):
        return self._current(entry[1], entry[2])

    def _lower_utility(self, left_key, left, right_key, right):
        left_value = (self._entry_count(left) + 1) ** 2 * right[0]
        right_value = (self._entry_count(right) + 1) ** 2 * left[0]
        if left_value != right_value:
            return left_value < right_value
        return left_key < right_key

    def _choose_victim(self, excluded):
        chosen = None
        for key, entry in self._entries.items():
            if key in excluded:
                continue
            if chosen is None or self._lower_utility(key, entry, chosen[0], chosen[1]):
                chosen = (key, entry)
        return chosen

    def access(self, key: int, size: int, now: int) -> list[int]:
        self._advance()

        entry = self._entries.get(key)
        if entry is not None:
            entry[1] = self._entry_count(entry) + 1
            entry[2] = self._epoch
            return []

        count = self._observe_miss(key)
        if size <= 0 or size > self.capacity_bytes:
            return []

        candidate_weight = (count + 1) ** 2
        needed = self._used + size - self.capacity_bytes
        plan = []
        excluded = set()
        freed = 0

        while freed < max(0, needed):
            selected = self._choose_victim(excluded)
            if selected is None:
                return []
            victim_key, victim = selected
            victim_count = self._entry_count(victim)
            if candidate_weight * victim[0] <= (victim_count + 1) ** 2 * size:
                return []
            plan.append((victim_key, victim))
            excluded.add(victim_key)
            freed += victim[0]

        evicted = []
        for victim_key, victim in plan:
            del self._entries[victim_key]
            self._used -= victim[0]
            self._remember(victim_key, self._entry_count(victim))
            evicted.append(victim_key)

        self._entries[key] = [size, count, self._epoch]
        self._used += size
        return evicted
