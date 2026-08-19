from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        try:
            self.capacity = max(0, int(capacity_bytes))
        except Exception:
            self.capacity = 0
        self.recent = OrderedDict()
        self.frequent = OrderedDict()
        self.recent_bytes = 0
        self.frequent_bytes = 0
        self.ghost_recent = OrderedDict()
        self.ghost_frequent = OrderedDict()
        self.target_recent = self.capacity // 2
        self.max_ghost = 4096

    def _remove_ghosts(self, key):
        self.ghost_recent.pop(key, None)
        self.ghost_frequent.pop(key, None)

    def _ghost_admission(self, key):
        step = max(1, self.capacity // 8)
        if key in self.ghost_recent:
            self.ghost_recent.pop(key, None)
            self.target_recent = min(self.capacity, self.target_recent + step)
            return True
        if key in self.ghost_frequent:
            self.ghost_frequent.pop(key, None)
            self.target_recent = max(0, self.target_recent - step)
            return True
        return False

    def _remember_ghost(self, key, size, frequent):
        self._remove_ghosts(key)
        bucket = self.ghost_frequent if frequent else self.ghost_recent
        bucket[key] = size
        bucket.move_to_end(key)
        while len(bucket) > self.max_ghost:
            bucket.popitem(last=False)

    def _evict(self, key, output):
        if key in self.recent:
            size = self.recent.pop(key)
            self.recent_bytes -= size
            self._remember_ghost(key, size, False)
        elif key in self.frequent:
            size = self.frequent.pop(key)
            self.frequent_bytes -= size
            self._remember_ghost(key, size, True)
        else:
            return False
        output.append(key)
        return True

    def _evict_oldest(self, bucket, protected, output):
        for key in bucket:
            if key != protected:
                return self._evict(key, output)
        return False

    def _trim(self, protected, output):
        while self.recent_bytes + self.frequent_bytes > self.capacity:
            if self.recent_bytes > self.target_recent:
                if self._evict_oldest(self.recent, protected, output):
                    continue
                if self._evict_oldest(self.frequent, protected, output):
                    continue
            else:
                if self._evict_oldest(self.frequent, protected, output):
                    continue
                if self._evict_oldest(self.recent, protected, output):
                    continue
            break

    def _evict_all(self, output):
        for key in list(self.recent):
            self._evict(key, output)
        for key in list(self.frequent):
            self._evict(key, output)

    def access(self, key: int, size: int, now: int) -> list[int]:
        del now
        try:
            size = max(0, int(size))
        except Exception:
            size = 0
        output = []

        if self.capacity <= 0 or size > self.capacity:
            self._evict_all(output)
            return output

        if key in self.recent:
            old_size = self.recent.pop(key)
            self.recent_bytes -= old_size
            self.frequent[key] = size
            self.frequent.move_to_end(key)
            self.frequent_bytes += size
            self._remove_ghosts(key)
            self._trim(key, output)
            return output

        if key in self.frequent:
            old_size = self.frequent[key]
            self.frequent[key] = size
            self.frequent.move_to_end(key)
            self.frequent_bytes += size - old_size
            self._remove_ghosts(key)
            self._trim(key, output)
            return output

        to_frequent = self._ghost_admission(key)
        self._remove_ghosts(key)
        if to_frequent:
            self.frequent[key] = size
            self.frequent_bytes += size
        else:
            self.recent[key] = size
            self.recent_bytes += size
        self._trim(key, output)
        return output
