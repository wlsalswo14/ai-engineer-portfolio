from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self._recent = OrderedDict()
        self._frequent = OrderedDict()
        self._recent_bytes = 0
        self._frequent_bytes = 0
        self._used = 0
        self._target = self.capacity_bytes // 2
        self._b1 = OrderedDict()
        self._b2 = OrderedDict()
        self._ghost_order = OrderedDict()
        self._ghost_limit = max(32, min(4096, self.capacity_bytes // 64 + 32))

    def _size(self, value):
        value = int(value)
        return max(0, value)

    def _remember_ghost(self, key, size, segment):
        self._b1.pop(key, None)
        self._b2.pop(key, None)
        self._ghost_order.pop(key, None)
        target = self._b1 if segment == 1 else self._b2
        target[key] = size
        self._ghost_order[key] = segment
        while len(self._ghost_order) > self._ghost_limit:
            old_key, old_segment = self._ghost_order.popitem(last=False)
            if old_segment == 1:
                self._b1.pop(old_key, None)
            else:
                self._b2.pop(old_key, None)

    def _ghost_hit(self, key, size):
        segment = None
        if key in self._b1:
            self._b1.pop(key, None)
            segment = 1
        elif key in self._b2:
            self._b2.pop(key, None)
            segment = 2
        if segment is None:
            return None
        self._ghost_order.pop(key, None)
        if self.capacity_bytes:
            step = max(1, min(self.capacity_bytes, size or 1))
            if segment == 1:
                self._target = min(self.capacity_bytes, self._target + step)
            else:
                self._target = max(0, self._target - step)
        return segment

    def _make_room(self, incoming, evicted, emitted):
        while self._used + incoming > self.capacity_bytes:
            if not self._recent and not self._frequent:
                break
            if self._recent and (self._recent_bytes > self._target or not self._frequent):
                key, size = self._recent.popitem(last=False)
                self._recent_bytes -= size
                segment = 1
            else:
                key, size = self._frequent.popitem(last=False)
                self._frequent_bytes -= size
                segment = 2
            self._used -= size
            self._remember_ghost(key, size, segment)
            if isinstance(key, int) and key not in emitted:
                emitted.add(key)
                evicted.append(key)

    def access(self, key: int, size: int, now: int) -> list[int]:
        requested = self._size(size)
        evicted = []
        emitted = set()

        if key in self._recent:
            old_size = self._recent.pop(key)
            self._recent_bytes -= old_size
            self._used -= old_size
            if requested > self.capacity_bytes:
                return [key] if isinstance(key, int) else []
            self._make_room(requested, evicted, emitted)
            self._frequent[key] = requested
            self._frequent_bytes += requested
            self._used += requested
            return evicted

        if key in self._frequent:
            old_size = self._frequent.pop(key)
            self._frequent_bytes -= old_size
            self._used -= old_size
            if requested > self.capacity_bytes:
                return [key] if isinstance(key, int) else []
            self._make_room(requested, evicted, emitted)
            self._frequent[key] = requested
            self._frequent_bytes += requested
            self._used += requested
            return evicted

        ghost_segment = self._ghost_hit(key, requested)
        if requested > self.capacity_bytes:
            return evicted

        self._make_room(requested, evicted, emitted)
        if ghost_segment is None:
            self._recent[key] = requested
            self._recent_bytes += requested
        else:
            self._frequent[key] = requested
            self._frequent_bytes += requested
        self._used += requested
        return evicted
