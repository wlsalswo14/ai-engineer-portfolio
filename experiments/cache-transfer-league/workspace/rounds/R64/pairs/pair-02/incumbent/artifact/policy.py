class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = int(capacity_bytes) if capacity_bytes > 0 else 0
        self.resident = {}
        self.bytes_used = 0
        self.protected_bytes = 0
        self.ticks = 0
        self.ghost = {}
        self.ghost_limit = 4096
        self.protected_target = (self.capacity_bytes * 3) // 4

    def _size(self, size):
        return int(size) if size > 0 else 0

    def _utility(self, record):
        age = self.ticks - record["last"]
        if age < 0:
            age = 0
        recency = 64 // (age + 1)
        queue_bonus = 2 if record["queue"] == 2 else 0
        return 1 + 4 * record["freq"] + recency + queue_bonus

    def _remember(self, key, record):
        self.ghost[key] = (record["freq"], self.ticks, record["birth"])
        if len(self.ghost) > self.ghost_limit:
            oldest = min(self.ghost, key=lambda candidate: self.ghost[candidate][2])
            del self.ghost[oldest]

    def _remove(self, key):
        record = self.resident.pop(key)
        self.bytes_used -= record["size"]
        if record["queue"] == 2:
            self.protected_bytes -= record["size"]
        self._remember(key, record)

    def _evict_all(self):
        victims = list(self.resident.keys())
        for key in victims:
            self._remove(key)
        return victims

    def _choose_victim(self, exclude=None, protected_only=False):
        candidates = []
        for key, record in self.resident.items():
            if key == exclude:
                continue
            if protected_only:
                if record["queue"] == 2:
                    candidates.append(key)
            elif record["queue"] == 1:
                candidates.append(key)
        if not candidates and not protected_only:
            for key, record in self.resident.items():
                if key != exclude:
                    candidates.append(key)
        if not candidates:
            return None
        best_key = None
        best_utility = 0
        best_cost = 1
        best_birth = 0
        for key in candidates:
            record = self.resident[key]
            utility = self._utility(record)
            cost = record["size"] if record["size"] > 0 else 1
            if best_key is None:
                choose = True
            else:
                left = utility * best_cost
                right = best_utility * cost
                choose = left < right
                if left == right:
                    choose = record["birth"] < best_birth
                    if record["birth"] == best_birth and key < best_key:
                        choose = True
            if choose:
                best_key = key
                best_utility = utility
                best_cost = cost
                best_birth = record["birth"]
        return best_key

    def _rebalance(self):
        while self.protected_bytes > self.protected_target:
            key = self._choose_victim(protected_only=True)
            if key is None:
                break
            record = self.resident[key]
            record["queue"] = 1
            self.protected_bytes -= record["size"]

    def _age(self):
        for record in self.resident.values():
            record["freq"] = max(1, (record["freq"] + 1) // 2)
            if (record["queue"] == 2 and
                    self.ticks - record["last"] > 512 and
                    record["freq"] <= 1):
                record["queue"] = 1
                self.protected_bytes -= record["size"]

    def access(self, key: int, size: int, now: int) -> list[int]:
        self.ticks += 1
        if self.ticks % 256 == 0:
            self._age()
        item_size = self._size(size)

        if key in self.resident:
            record = self.resident[key]
            old_size = record["size"]
            if old_size != item_size:
                self.bytes_used += item_size - old_size
                record["size"] = item_size
                if record["queue"] == 2:
                    self.protected_bytes += item_size - old_size
            record["freq"] = min(64, record["freq"] + 1)
            record["last"] = self.ticks
            if record["queue"] == 1:
                record["queue"] = 2
                self.protected_bytes += record["size"]
            self._rebalance()

            if item_size > self.capacity_bytes:
                return self._evict_all()

            victims = []
            while self.bytes_used > self.capacity_bytes:
                victim = self._choose_victim(exclude=key)
                if victim is None:
                    victim = key
                victims.append(victim)
                self._remove(victim)
            return victims

        if self.capacity_bytes == 0 or item_size > self.capacity_bytes:
            return self._evict_all()

        victims = []
        while self.bytes_used + item_size > self.capacity_bytes:
            victim = self._choose_victim()
            if victim is None:
                break
            victims.append(victim)
            self._remove(victim)

        prior = self.ghost.pop(key, None)
        protected = prior is not None and self.ticks - prior[1] <= 512
        frequency = max(1, prior[0] if prior is not None else 1)
        self.resident[key] = {
            "size": item_size,
            "freq": min(64, frequency),
            "last": self.ticks,
            "birth": self.ticks,
            "queue": 2 if protected else 1,
        }
        self.bytes_used += item_size
        if protected:
            self.protected_bytes += item_size
            self._rebalance()
        return victims
