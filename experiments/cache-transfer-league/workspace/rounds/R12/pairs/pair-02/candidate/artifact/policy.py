from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.entries = {}
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.used_bytes = 0
        self.probation_bytes = 0
        self.protected_bytes = 0
        self.tick = 0
        self.lower_target = max(1, self.capacity_bytes // 4) if self.capacity_bytes else 0
        self.upper_target = max(self.lower_target, (self.capacity_bytes * 3) // 4) if self.capacity_bytes else 0
        self.protected_target = max(1, self.capacity_bytes // 2) if self.capacity_bytes else 0
        self.ghost_probation = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.ghost_bytes = 0
        self.ghost_limit = max(128, min(4096, self.capacity_bytes // 64 + 128))
        self.mask = (1 << 64) - 1
        self.sketch_width = 2048
        self.sketch = [[0] * self.sketch_width for _ in range(4)]
        self.seeds = (0x243F6A8885A308D3, 0x13198A2E03707344, 0xA4093822299F31D0, 0x082EFA98EC4E6C89)
        self.observations = 0

    def _mix(self, key: int, seed: int) -> int:
        x = (int(key) & self.mask) ^ seed
        x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & self.mask
        x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & self.mask
        return (x ^ (x >> 31)) & self.mask

    def _observe(self, key: int) -> None:
        self.observations += 1
        for row, seed in enumerate(self.seeds):
            index = self._mix(key, seed) % self.sketch_width
            if self.sketch[row][index] < 255:
                self.sketch[row][index] += 1
        if (self.observations & 65535) == 0:
            for row in self.sketch:
                for index, value in enumerate(row):
                    row[index] = value >> 1

    def _estimate(self, key: int) -> int:
        estimate = 255
        for row, seed in enumerate(self.seeds):
            index = self._mix(key, seed) % self.sketch_width
            estimate = min(estimate, self.sketch[row][index])
        return max(1, estimate)

    def _remember_ghost(self, key, size: int, segment: int) -> None:
        for ghosts in (self.ghost_probation, self.ghost_protected):
            old = ghosts.pop(key, None)
            if old is not None:
                self.ghost_bytes -= old[0]
        target = self.ghost_protected if segment == 1 else self.ghost_probation
        target[key] = (size, self.tick)
        self.ghost_bytes += size
        while len(self.ghost_probation) + len(self.ghost_protected) > self.ghost_limit:
            probation_first = next(iter(self.ghost_probation.items()), None)
            protected_first = next(iter(self.ghost_protected.items()), None)
            if protected_first is None or (probation_first is not None and probation_first[1][1] <= protected_first[1][1]):
                _, value = self.ghost_probation.popitem(last=False)
            else:
                _, value = self.ghost_protected.popitem(last=False)
            self.ghost_bytes -= value[0]

    def _take_ghost(self, key):
        value = self.ghost_probation.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]
            return 0
        value = self.ghost_protected.pop(key, None)
        if value is not None:
            self.ghost_bytes -= value[0]
            return 1
        return None

    def _adapt(self, ghost_class) -> None:
        if not self.capacity_bytes:
            return
        step = max(1, self.capacity_bytes // 8)
        if ghost_class == 0:
            self.protected_target = max(self.lower_target, self.protected_target - step)
        elif ghost_class == 1:
            self.protected_target = min(self.upper_target, self.protected_target + step)

    def _rebalance(self) -> None:
        while self.protected and self.protected_bytes > self.protected_target:
            key, _ = self.protected.popitem(last=False)
            size = self.entries[key][0]
            self.protected_bytes -= size
            self.probation[key] = None
            self.probation_bytes += size
            self.entries[key][1] = 0

    def _value(self, key) -> int:
        size, segment, frequency, last = self.entries[key]
        age = max(0, self.tick - last)
        decay = min(8, age // 128)
        effective_frequency = max(1, frequency >> decay)
        recency = 256 - min(256, age)
        value = effective_frequency * 256 + recency
        if segment == 1:
            value += 4096
        return value

    def _pick_victim(self, excluded):
        best_key = None
        best_value = None
        for container in (self.probation, self.protected):
            examined = 0
            for key in container:
                if key in excluded:
                    continue
                if examined >= 64:
                    break
                examined += 1
                value = self._value(key)
                if best_value is None or value < best_value:
                    best_key = key
                    best_value = value
        return best_key

    def _can_replace(self, candidate_frequency: int, ghost_class, candidate_size: int, victim) -> bool:
        record = self.entries[victim]
        if record[1] != 1 or ghost_class == 1:
            return True
        victim_frequency = max(1, record[2])
        if candidate_frequency <= victim_frequency:
            return False
        victim_size = max(1, record[0])
        if candidate_size > record[0] and candidate_frequency * victim_size < victim_frequency * candidate_size:
            return False
        return True

    def _remove(self, key, remember: bool = True) -> None:
        size, segment, _, _ = self.entries.pop(key)
        if segment == 0:
            self.probation.pop(key, None)
            self.probation_bytes -= size
        else:
            self.protected.pop(key, None)
            self.protected_bytes -= size
        self.used_bytes -= size
        if remember:
            self._remember_ghost(key, size, segment)

    def _hit(self, key) -> None:
        record = self.entries[key]
        size, segment = record[0], record[1]
        record[2] = min(65535, record[2] + 1)
        record[3] = self.tick
        if segment == 0:
            self.probation.pop(key, None)
            self.probation_bytes -= size
            self.protected[key] = None
            self.protected_bytes += size
            record[1] = 1
        else:
            self.protected.move_to_end(key)
        self._rebalance()

    def access(self, key: int, size: int, now: int) -> list[int]:
        self.tick += 1
        request_size = max(0, int(size))
        self._observe(key)
        if key in self.entries:
            self._hit(key)
            return []
        if self.capacity_bytes == 0 or request_size > self.capacity_bytes:
            return []

        ghost_class = self._take_ghost(key)
        self._adapt(ghost_class)
        self._rebalance()
        candidate_frequency = self._estimate(key)
        victims = []
        excluded = set()
        free_bytes = self.capacity_bytes - self.used_bytes
        while free_bytes < request_size:
            victim = self._pick_victim(excluded)
            if victim is None:
                return []
            victim_size = self.entries[victim][0]
            excluded.add(victim)
            if victim_size == 0:
                continue
            if not self._can_replace(candidate_frequency, ghost_class, request_size, victim):
                return []
            victims.append(victim)
            free_bytes += victim_size

        evicted = []
        for victim in victims:
            self._remove(victim, True)
            evicted.append(victim)

        segment = 1 if ghost_class == 1 else 0
        frequency = min(65535, max(1, candidate_frequency))
        self.entries[key] = [request_size, segment, frequency, self.tick]
        if segment == 0:
            self.probation[key] = None
            self.probation_bytes += request_size
        else:
            self.protected[key] = None
            self.protected_bytes += request_size
        self.used_bytes += request_size
        self._rebalance()
        return evicted
