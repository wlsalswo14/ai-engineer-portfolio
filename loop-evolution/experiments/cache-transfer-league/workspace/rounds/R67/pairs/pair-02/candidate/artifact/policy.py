from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity = max(0, int(capacity_bytes))
        self.recent = OrderedDict()
        self.protected = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_protected = OrderedDict()
        self.recent_bytes = 0
        self.protected_bytes = 0
        self.used = 0
        self.protected_target = self.capacity // 2
        self._serial = 0
        self._ghost_bytes = 0
        self._ghost_limit = max(64, min(1 << 20, 2 * max(1, self.capacity)))
        self._ghost_count_limit = 4096
        self._candidate_before = None
        self._candidate_change_active = False

    def _drop_ghost(self, key):
        for ghosts in (self.ghost_recent, self.ghost_protected):
            value = ghosts.pop(key, None)
            if value is not None:
                self._ghost_bytes -= value[0]

    def _remember_ghost(self, key, size, protected):
        self._drop_ghost(key)
        self._serial += 1
        value = (max(0, int(size)), self._serial)
        ghosts = self.ghost_protected if protected else self.ghost_recent
        ghosts[key] = value
        self._ghost_bytes += value[0]
        self._trim_ghosts()

    def _trim_ghosts(self):
        while (self._ghost_bytes > self._ghost_limit or
               len(self.ghost_recent) + len(self.ghost_protected) > self._ghost_count_limit):
            selected = self.ghost_recent
            if not selected:
                selected = self.ghost_protected
            elif self.ghost_protected:
                r = next(iter(self.ghost_recent.values()))[1]
                p = next(iter(self.ghost_protected.values()))[1]
                if p < r:
                    selected = self.ghost_protected
            _, value = selected.popitem(last=False)
            self._ghost_bytes -= value[0]

    def _begin_candidate_change(self):
        self._candidate_before = self.protected_target
        self._candidate_change_active = True

    def _rollback_candidate_change(self):
        if self._candidate_change_active:
            self.protected_target = self._candidate_before
        self._candidate_before = None
        self._candidate_change_active = False

    def _commit_candidate_change(self):
        self._candidate_before = None
        self._candidate_change_active = False

    def _normatively_valid(self):
        return (0 <= self.protected_target <= self.capacity and
                self.used == self.recent_bytes + self.protected_bytes and
                0 <= self.used <= self.capacity and
                self.recent_bytes >= 0 and self.protected_bytes >= 0)

    def _adjust_target(self, kind):
        if self.capacity <= 0:
            return
        self._begin_candidate_change()
        b_recent = sum(value[0] for value in self.ghost_recent.values())
        b_protected = sum(value[0] for value in self.ghost_protected.values())
        if kind == 1:
            delta = self.capacity if b_recent == 0 else max(1, min(self.capacity, b_protected // b_recent or 1))
            self.protected_target = max(0, min(self.capacity, self.protected_target - delta))
        else:
            delta = self.capacity if b_protected == 0 else max(1, min(self.capacity, b_recent // b_protected or 1))
            self.protected_target = max(0, min(self.capacity, self.protected_target + delta))
        if not self._normatively_valid():
            self._rollback_candidate_change()

    def _remove_resident(self, key):
        value = self.recent.pop(key, None)
        if value is not None:
            self.recent_bytes -= value
            self.used -= value
            return value, 1
        value = self.protected.pop(key, None)
        if value is not None:
            self.protected_bytes -= value
            self.used -= value
            return value, 2
        return 0, 0

    def _demote_excess_protected(self):
        while self.protected and self.protected_bytes > self.protected_target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.recent[key] = size
            self.recent_bytes += size

    def _evict_one(self, ghost_kind):
        prefer_recent = bool(self.recent) and not self.protected
        if self.recent and self.protected:
            if ghost_kind == 2:
                prefer_recent = True
            else:
                prefer_recent = self.recent_bytes >= self.protected_target
        if prefer_recent and self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, False)
            return key
        if self.protected:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, True)
            return key
        if self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            self.used -= size
            self._remember_ghost(key, size, False)
            return key
        return None

    def _make_room(self, incoming, ghost_kind):
        evicted = []
        while self.used + incoming > self.capacity:
            key = self._evict_one(ghost_kind)
            if key is None:
                break
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        key = int(key)
        size = max(0, int(size))

        resident = key in self.recent or key in self.protected
        if resident:
            _, kind = self._remove_resident(key)
            self._drop_ghost(key)
            if size > self.capacity:
                return [key]
            evicted = self._make_room(size, 0)
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            if kind == 1:
                self._demote_excess_protected()
            return evicted

        if size > self.capacity:
            return []

        ghost_kind = 0
        if key in self.ghost_recent:
            ghost_kind = 1
        elif key in self.ghost_protected:
            ghost_kind = 2

        if ghost_kind:
            self._adjust_target(ghost_kind)
            self._drop_ghost(key)

        evicted = self._make_room(size, ghost_kind)
        if ghost_kind:
            self.protected[key] = size
            self.protected_bytes += size
            self.used += size
            self._demote_excess_protected()
        else:
            self.recent[key] = size
            self.recent_bytes += size
            self.used += size

        if self._candidate_change_active:
            if self._normatively_valid():
                self._commit_candidate_change()
            else:
                self._rollback_candidate_change()
        return evicted
