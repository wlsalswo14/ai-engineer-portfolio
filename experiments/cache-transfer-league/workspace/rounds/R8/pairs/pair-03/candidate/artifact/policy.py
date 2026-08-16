from collections import deque


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self._cache = {}
        self._used_bytes = 0
        self._clock = 0
        self._next_decay = 256
        self._history = {}
        self._history_queue = deque()

    def _remember(self, key, count):
        previous = self._history.get(key)
        if previous is not None:
            count = max(count, previous[0])
        count = min(255, count)
        stamp = self._clock
        self._history[key] = (count, stamp)
        self._history_queue.append((key, stamp))
        while len(self._history_queue) > 4096:
            old_key, old_stamp = self._history_queue.popleft()
            current = self._history.get(old_key)
            if current is not None and current[1] == old_stamp:
                del self._history[old_key]

    def _forget(self, key):
        self._history.pop(key, None)

    def _decay(self):
        for entry in self._cache.values():
            entry[1] = max(1, entry[1] // 2)
        for key, record in self._history.items():
            self._history[key] = (max(1, record[0] // 2), record[1])

    def _value(self, size, frequency, last):
        age = max(0, self._clock - last)
        return (frequency * 16384) // ((4096 + age) * (4 + size.bit_length()))

    def access(self, key: int, size: int, now: int) -> list[int]:
        del now
        self._clock += 1
        if self._clock >= self._next_decay:
            self._decay()
            self._next_decay += 256

        entry = self._cache.get(key)
        if entry is not None:
            entry[1] = min(255, entry[1] + 1)
            entry[2] = self._clock
            return []

        size = max(0, size)
        record = self._history.get(key)
        prior_count = 0 if record is None else record[0]
        frequency = min(255, prior_count + 1)

        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            self._remember(key, frequency)
            return []

        required = self._used_bytes + size - self.capacity_bytes
        if required > 0:
            candidates = sorted(
                self._cache.items(),
                key=lambda pair: (
                    self._value(pair[1][0], pair[1][1], pair[1][2]),
                    pair[1][2],
                    pair[0],
                ),
            )
            candidate_value = self._value(size, frequency, self._clock)
            selected = []
            freed = 0
            for old_key, old_entry in candidates:
                old_value = self._value(old_entry[0], old_entry[1], old_entry[2])
                if prior_count == 0:
                    if old_value != 0:
                        break
                elif candidate_value <= old_value:
                    break
                selected.append((old_key, old_entry))
                freed += old_entry[0]
                if freed >= required:
                    break

            if freed < required:
                self._remember(key, frequency)
                return []

            evicted = []
            for old_key, old_entry in selected:
                del self._cache[old_key]
                self._used_bytes -= old_entry[0]
                self._remember(old_key, old_entry[1])
                evicted.append(old_key)
        else:
            evicted = []

        self._cache[key] = [size, frequency, self._clock]
        self._used_bytes += size
        self._forget(key)
        return evicted
