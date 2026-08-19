from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes):
        try:
            capacity = int(capacity_bytes)
        except Exception:
            capacity = 0
        self.capacity_bytes = max(0, capacity)
        self.used_bytes = 0
        self._items = {}
        self._probation = OrderedDict()
        self._protected = OrderedDict()
        self._ghost = OrderedDict()
        self._ghost_limit = 1024
        self._seq = 0

    def access(self, key, size, now):
        self._seq += 1
        if isinstance(key, bool) or not isinstance(key, int):
            return []
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            return []

        evicted = []
        if size > self.capacity_bytes:
            if key in self._items:
                self._remove(key, evicted, remember=True)
            return evicted

        item = self._items.get(key)
        if item is not None:
            self.used_bytes += size - item["size"]
            item["size"] = size
            item["freq"] = min(64, item["freq"] + 1)
            item["last"] = self._seq
            if item["protected"]:
                self._protected.move_to_end(key)
            else:
                self._probation.pop(key, None)
                item["protected"] = True
                self._protected[key] = None
            self._ghost.pop(key, None)
            self._rebalance_protected()
            self._trim(evicted, exclude=key)
            return evicted

        protected = key in self._ghost
        self._ghost.pop(key, None)
        item = {
            "size": size,
            "freq": 1,
            "last": self._seq,
            "protected": protected,
        }
        self._items[key] = item
        self.used_bytes += size
        if protected:
            self._protected[key] = None
        else:
            self._probation[key] = None
        self._rebalance_protected()
        self._trim(evicted)
        return evicted

    def _rebalance_protected(self):
        target = (self.capacity_bytes * 3) // 4
        protected_bytes = sum(
            self._items[key]["size"]
            for key in self._protected
            if key in self._items
        )
        while protected_bytes > target and self._protected:
            key = next(iter(self._protected))
            item = self._items.get(key)
            self._protected.pop(key, None)
            if item is None:
                continue
            item["protected"] = False
            self._probation[key] = None
            protected_bytes -= item["size"]

    def _trim(self, evicted, exclude=None):
        seen = set(evicted)
        while self.used_bytes > self.capacity_bytes:
            key = self._victim(exclude)
            if key is None:
                break
            if key in seen:
                break
            self._remove(key, evicted, remember=True)
            seen.add(key)

    def _victim(self, exclude=None):
        pool = self._probation if self._probation else self._protected
        best_key = None
        best_rank = None
        for key in pool:
            if key == exclude:
                continue
            item = self._items.get(key)
            if item is None:
                continue
            age = self._seq - item["last"]
            utility = 8 * min(64, item["freq"]) + max(0, 32 - age)
            ratio = (utility * 1048576) // max(1, item["size"])
            rank = (ratio, utility, -age, -item["size"], -item["last"])
            if best_rank is None or rank < best_rank:
                best_rank = rank
                best_key = key
        return best_key

    def _remove(self, key, evicted, remember):
        item = self._items.pop(key, None)
        if item is None:
            return
        self._probation.pop(key, None)
        self._protected.pop(key, None)
        self.used_bytes -= item["size"]
        if self.used_bytes < 0:
            self.used_bytes = 0
        if key not in evicted:
            evicted.append(key)
        if remember:
            self._ghost[key] = None
            self._ghost.move_to_end(key)
            while len(self._ghost) > self._ghost_limit:
                self._ghost.popitem(last=False)
