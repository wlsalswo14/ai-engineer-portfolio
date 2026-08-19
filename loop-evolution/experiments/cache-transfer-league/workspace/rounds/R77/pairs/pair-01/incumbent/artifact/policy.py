from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self._a = OrderedDict()
        self._b = OrderedDict()
        self._b1 = OrderedDict()
        self._b2 = OrderedDict()
        self._a_bytes = 0
        self._b_bytes = 0
        self._b1_bytes = 0
        self._b2_bytes = 0
        self._used = 0
        self._target = self.capacity // 4
        self._serial = 0
        self._history_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self._history_count_limit = 4096

    def _forget_history(self, key):
        value = self._b1.pop(key, None)
        if value is not None:
            self._b1_bytes -= value[0]
        value = self._b2.pop(key, None)
        if value is not None:
            self._b2_bytes -= value[0]

    def _remember(self, key, size, kind):
        self._forget_history(key)
        self._serial += 1
        value = (size, self._serial)
        if kind == 1:
            self._b1[key] = value
            self._b1_bytes += size
        else:
            self._b2[key] = value
            self._b2_bytes += size
        self._trim_history()

    def _trim_history(self):
        while (self._b1_bytes + self._b2_bytes > self._history_limit or
               len(self._b1) + len(self._b2) > self._history_count_limit):
            if not self._b1:
                _, value = self._b2.popitem(last=False)
                self._b2_bytes -= value[0]
                continue
            if not self._b2:
                _, value = self._b1.popitem(last=False)
                self._b1_bytes -= value[0]
                continue
            first_a = next(iter(self._b1.values()))[1]
            first_b = next(iter(self._b2.values()))[1]
            if first_a <= first_b:
                _, value = self._b1.popitem(last=False)
                self._b1_bytes -= value[0]
            else:
                _, value = self._b2.popitem(last=False)
                self._b2_bytes -= value[0]

    def _take(self, key):
        value = self._a.pop(key, None)
        if value is not None:
            self._a_bytes -= value[0]
            self._used -= value[0]
            return value
        value = self._b.pop(key, None)
        if value is not None:
            self._b_bytes -= value[0]
            self._used -= value[0]
            return value
        return None

    def _put(self, queue, key, size, frequency):
        self._serial += 1
        value = (size, frequency, self._serial)
        queue[key] = value
        if queue is self._a:
            self._a_bytes += size
        else:
            self._b_bytes += size
        self._used += size

    def _retune(self, kind, old_size):
        if self.capacity <= 0:
            return
        step = max(1, min(self.capacity, old_size))
        if kind == 1:
            self._target = min(self.capacity, self._target + step)
        else:
            self._target = max(0, self._target - step)

    def _choose_a(self, kind):
        if not self._a:
            return False
        if not self._b:
            return True
        if self._a_bytes > self._target:
            return True
        return kind == 2 and self._a_bytes == self._target

    def _make_room(self, incoming, kind):
        evicted = []
        while self._used + incoming > self.capacity:
            use_a = self._choose_a(kind)
            queue = self._a if use_a else self._b
            if not queue:
                queue = self._b if use_a else self._a
            if not queue:
                break
            key, value = queue.popitem(last=False)
            amount = value[0]
            if queue is self._a:
                self._a_bytes -= amount
                ghost_kind = 1
            else:
                self._b_bytes -= amount
                ghost_kind = 2
            self._used -= amount
            self._remember(key, amount, ghost_kind)
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))
        resident = key in self._a or key in self._b

        if resident:
            value = self._take(key)
            if size == 0 or size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            self._forget_history(key)
            self._put(self._b, key, size, value[1] + 1)
            return evicted

        if size == 0 or size > self.capacity or self.capacity <= 0:
            return []

        if key in self._b1:
            old_size = self._b1[key][0]
            self._retune(1, old_size)
            self._forget_history(key)
            evicted = self._make_room(size, 1)
            self._put(self._b, key, size, 2)
            return evicted

        if key in self._b2:
            old_size = self._b2[key][0]
            self._retune(2, old_size)
            self._forget_history(key)
            evicted = self._make_room(size, 2)
            self._put(self._b, key, size, 2)
            return evicted

        evicted = self._make_room(size, 0)
        self._put(self._a, key, size, 1)
        return evicted
