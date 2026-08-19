from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        self.capacity = max(0, int(capacity_bytes))
        self.target = 0
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.resident_bytes = 0
        self.ghost_limit = 4096

    def _trim_ghost(self, table):
        total = sum(table.values())
        while table and (total > self.capacity or len(table) > self.ghost_limit):
            _, value = table.popitem(last=False)
            total -= value

    def _remember(self, key, size, frequent):
        if self.capacity <= 0:
            return
        size = min(max(0, int(size)), self.capacity)
        self.ghost_recent.pop(key, None)
        self.ghost_frequent.pop(key, None)
        table = self.ghost_frequent if frequent else self.ghost_recent
        table[key] = size
        self._trim_ghost(table)

    def _evict_one(self, result):
        if self.recent and (self.recent_bytes > self.target or not self.frequent):
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            source_frequent = False
        elif self.frequent:
            key, size = self.frequent.popitem(last=False)
            self.frequent_bytes -= size
            source_frequent = True
        elif self.recent:
            key, size = self.recent.popitem(last=False)
            self.recent_bytes -= size
            source_frequent = False
        else:
            return False
        self.resident_bytes -= size
        self._remember(key, size, source_frequent)
        result.append(key)
        return True

    def _make_room(self, size, result):
        while self.resident_bytes + size > self.capacity:
            if not self._evict_one(result):
                break

    def access(self, key, size, now):
        size = max(0, int(size))
        result = []

        if key in self.recent:
            old = self.recent.pop(key)
            self.recent_bytes -= old
            self.resident_bytes -= old
            if size > self.capacity:
                self._remember(key, size, False)
                result.append(key)
                return result
            self._make_room(size, result)
            self.frequent[key] = size
            self.frequent_bytes += size
            self.resident_bytes += size
            return result

        if key in self.frequent:
            old = self.frequent.pop(key)
            self.frequent_bytes -= old
            self.resident_bytes -= old
            if size > self.capacity:
                self._remember(key, size, True)
                result.append(key)
                return result
            self._make_room(size, result)
            self.frequent[key] = size
            self.frequent_bytes += size
            self.resident_bytes += size
            return result

        if size > self.capacity:
            return result

        if key in self.ghost_recent:
            self.ghost_recent.pop(key)
            self.target = min(self.capacity, self.target + max(1, min(size, self.capacity)))
            destination = self.frequent
            destination_is_frequent = True
        elif key in self.ghost_frequent:
            self.ghost_frequent.pop(key)
            self.target = max(0, self.target - max(1, min(size, self.capacity)))
            destination = self.frequent
            destination_is_frequent = True
        else:
            destination = self.recent
            destination_is_frequent = False

        self._make_room(size, result)
        destination[key] = size
        if destination_is_frequent:
            self.frequent_bytes += size
        else:
            self.recent_bytes += size
        self.resident_bytes += size
        return result
