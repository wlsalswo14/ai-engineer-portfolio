from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.used = 0
        self.recent_target = self.capacity // 2
        self._ghost_serial = 0
        self._ghost_bytes = 0
        self._ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self._ghost_count_limit = 4096

    def _snapshot(self):
        return (
            self.recent.copy(),
            self.frequent.copy(),
            self.ghost_recent.copy(),
            self.ghost_frequent.copy(),
            self.recent_bytes,
            self.frequent_bytes,
            self.used,
            self.recent_target,
            self._ghost_serial,
            self._ghost_bytes,
        )

    def _restore(self, state):
        (
            self.recent,
            self.frequent,
            self.ghost_recent,
            self.ghost_frequent,
            self.recent_bytes,
            self.frequent_bytes,
            self.used,
            self.recent_target,
            self._ghost_serial,
            self._ghost_bytes,
        ) = state

    def _valid(self):
        if self.used < 0 or self.used > self.capacity:
            return False
        if self.recent_bytes < 0 or self.frequent_bytes < 0:
            return False
        if self.recent_bytes + self.frequent_bytes != self.used:
            return False
        if not 0 <= self.recent_target <= self.capacity:
            return False
        if set(self.recent).intersection(self.frequent):
            return False
        return True

    def _drop_ghost(self, key):
        value = self.ghost_recent.pop(key, None)
        if value is not None:
            self._ghost_bytes -= value[0]
        value = self.ghost_frequent.pop(key, None)
        if value is not None:
            self._ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, kind):
        self._drop_ghost(key)
        self._ghost_serial += 1
        value = (max(0, int(size)), self._ghost_serial)
        ghosts = self.ghost_recent if kind == 1 else self.ghost_frequent
        ghosts[key] = value
        self._ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (
            self._ghost_bytes > self._ghost_limit
            or len(self.ghost_recent) + len(self.ghost_frequent) > self._ghost_count_limit
        ):
            recent_serial = None
            frequent_serial = None
            if self.ghost_recent:
                recent_serial = next(iter(self.ghost_recent.values()))[1]
            if self.ghost_frequent:
                frequent_serial = next(iter(self.ghost_frequent.values()))[1]
            if frequent_serial is None or (
                recent_serial is not None and recent_serial < frequent_serial
            ):
                _, value = self.ghost_recent.popitem(last=False)
            else:
                _, value = self.ghost_frequent.popitem(last=False)
            self._ghost_bytes -= value[0]

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        recent_bytes = sum(value[0] for value in self.ghost_recent.values())
        frequent_bytes = sum(value[0] for value in self.ghost_frequent.values())
        if kind == 1:
            delta = self.capacity if recent_bytes == 0 else max(
                1, min(self.capacity, frequent_bytes // recent_bytes or 1)
            )
            self.recent_target = min(self.capacity, self.recent_target + delta)
        else:
            delta = self.capacity if frequent_bytes == 0 else max(
                1, min(self.capacity, recent_bytes // frequent_bytes or 1)
            )
            self.recent_target = max(0, self.recent_target - delta)

    def _remove_resident(self, key):
        value = self.recent.pop(key, None)
        if value is not None:
            self.recent_bytes -= value
            self.used -= value
            return value, 1
        value = self.frequent.pop(key, None)
        if value is not None:
            self.frequent_bytes -= value
            self.used -= value
            return value, 2
        return 0, 0

    def _evict_one(self, prefer_recent):
        if prefer_recent and self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 1)
            return key
        if self.frequent:
            key, size = self.frequent.popitem(last=False)
            self.frequent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 2)
            return key
        if self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, 1)
            return key
        return None

    def _make_room(self, incoming, ghost_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            prefer_recent = self.recent_bytes > self.recent_target
            if ghost_kind == 1 and self.recent_bytes >= self.recent_target:
                prefer_recent = True
            key = self._evict_one(prefer_recent)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        del now
        state = self._snapshot()
        key = int(key)
        size = max(0, int(size))

        if key in self.recent or key in self.frequent:
            self._remove_resident(key)
            if size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            self._drop_ghost(key)
            self.frequent[key] = size
            self.frequent_bytes += size
            self.used += size
        else:
            ghost_kind = 0
            if key in self.ghost_recent:
                ghost_kind = 1
            elif key in self.ghost_frequent:
                ghost_kind = 2

            if size > self.capacity:
                return []

            if ghost_kind:
                self._adjust_target(ghost_kind)
                self._drop_ghost(key)

            evicted = self._make_room(size, ghost_kind)
            if ghost_kind:
                self.frequent[key] = size
                self.frequent_bytes += size
            else:
                self.recent[key] = size
                self.recent_bytes += size
            self.used += size

        if not self._valid():
            self._restore(state)
            return []
        return evicted
