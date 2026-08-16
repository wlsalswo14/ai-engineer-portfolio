class Policy:
    def __init__(self, capacity_bytes):
        try:
            capacity = int(capacity_bytes)
        except (TypeError, ValueError, OverflowError):
            capacity = 0
        self.capacity_bytes = max(0, capacity)
        self.items = {}
        self.ghost = {}
        self.used = 0
        self.protected_bytes = 0
        self.protected_limit = (self.capacity_bytes * 7) // 10
        self.tick = 0
        self.last_now = None

    def _size(self, value):
        try:
            value = int(value)
        except (TypeError, ValueError, OverflowError):
            value = 1
        return max(1, value)

    def _remember(self, key, frequency):
        if type(key) is not int:
            return
        self.ghost[key] = (frequency, self.tick)
        if len(self.ghost) > 4096:
            oldest = min(self.ghost, key=lambda item: self.ghost[item][1])
            del self.ghost[oldest]

    def _remove(self, key):
        item = self.items.pop(key, None)
        if item is None:
            return
        size, frequency, last, protected = item
        self.used -= size
        if protected:
            self.protected_bytes -= size
        self._remember(key, frequency)

    def _score(self, key):
        size, frequency, last, protected = self.items[key]
        age = max(0, self.tick - last)
        recency = 100000 // (age + 1)
        value = frequency * 10000 + recency
        if protected:
            value += 5000
        return value / size

    def _victims(self, required, exclude=None):
        if required <= 0:
            return []
        ordered = sorted(
            self.items,
            key=lambda key: (self._score(key), self.items[key][2], self.items[key][1], key),
        )
        victims = []
        remaining = required
        for key in ordered:
            if key == exclude:
                continue
            victims.append(key)
            remaining -= self.items[key][0]
            if remaining <= 0:
                break
        return victims

    def _rebalance(self):
        while self.protected_bytes > self.protected_limit:
            protected = [key for key, item in self.items.items() if item[3]]
            if not protected:
                break
            key = min(
                protected,
                key=lambda item: (self.items[item][2], self.items[item][1], item),
            )
            entry = self.items[key]
            entry[3] = False
            self.protected_bytes -= entry[0]

    def _age(self):
        if self.tick % 64 == 0:
            for item in self.items.values():
                item[1] = max(1, (item[1] + 1) // 2)

        try:
            current_now = int(self.last_now if self.last_now is None else self.last_now)
        except (TypeError, ValueError, OverflowError):
            current_now = None
        return current_now

    def access(self, key, size, now):
        self.tick += 1
        self._age()

        try:
            observed_now = int(now)
        except (TypeError, ValueError, OverflowError):
            observed_now = None
        if observed_now is not None:
            if self.last_now is not None and observed_now > self.last_now + 32:
                decay = min(8, (observed_now - self.last_now) // 32)
                for item in self.items.values():
                    item[1] = max(1, item[1] - decay)
            self.last_now = observed_now

        if type(key) is not int:
            return []

        if self.capacity_bytes == 0:
            evicted = list(self.items)
            for item_key in evicted:
                self._remove(item_key)
            return evicted

        requested = self._size(size)
        if requested > self.capacity_bytes:
            evicted = list(self.items)
            for item_key in evicted:
                self._remove(item_key)
            return evicted

        if key in self.items:
            item = self.items[key]
            old_size = item[0]
            if requested < old_size:
                difference = old_size - requested
                item[0] = requested
                self.used -= difference
                if item[3]:
                    self.protected_bytes -= difference
            elif requested > old_size:
                needed = requested - old_size
                victims = self._victims(needed, exclude=key)
                freed = sum(self.items[item_key][0] for item_key in victims)
                if freed < needed:
                    evicted = victims + [key]
                    for item_key in evicted:
                        self._remove(item_key)
                    return evicted
                for item_key in victims:
                    self._remove(item_key)
                item = self.items[key]
                item[0] = requested
                self.used += needed

            item[1] = min(64, item[1] + 1)
            item[2] = self.tick
            if not item[3]:
                item[3] = True
                self.protected_bytes += item[0]
            self._rebalance()
            return []

        record = self.ghost.pop(key, None)
        frequency = 1 if record is None else min(32, record[0] + 1)
        needed = requested - (self.capacity_bytes - self.used)
        victims = self._victims(needed)
        for item_key in victims:
            self._remove(item_key)

        if self.used + requested > self.capacity_bytes:
            remainder = list(self.items)
            for item_key in remainder:
                self._remove(item_key)
            victims.extend(remainder)

        self.items[key] = [requested, frequency, self.tick, False]
        self.used += requested
        self._rebalance()
        return victims
