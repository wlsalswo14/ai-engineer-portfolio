from collections import deque
from heapq import heappop, heappush


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.items = {}
        self.used_bytes = 0
        self.recent_bytes = 0
        self.target_recent = (self.capacity_bytes * 3) // 5
        self.recent_heap = []
        self.hot_heap = []
        self.ghosts = {}
        self.ghost_queue = deque()
        self.ghost_serial = 0
        self.ghost_limit = max(256, min(8192, self.capacity_bytes // 64 + 256))
        self.tick = 0
        self.decay_period = 1024

    def _touch(self, key, item):
        item[4] += 1
        if item[3] == "r":
            heappush(self.recent_heap, (item[2], item[4], key))
        else:
            heappush(self.hot_heap, (item[1], -item[0], item[2], item[4], key))

    def _remember(self, key, segment):
        self.ghost_serial += 1
        serial = self.ghost_serial
        self.ghosts[key] = (segment, serial)
        self.ghost_queue.append((serial, key))
        while len(self.ghost_queue) > self.ghost_limit:
            old_serial, old_key = self.ghost_queue.popleft()
            current = self.ghosts.get(old_key)
            if current is not None and current[1] == old_serial:
                del self.ghosts[old_key]

    def _decay(self):
        for key, item in list(self.items.items()):
            if item[3] != "h":
                continue
            item[1] = max(1, item[1] // 2)
            if item[1] == 1:
                item[3] = "r"
                self.recent_bytes += item[0]
            self._touch(key, item)

    def _maybe_rebuild(self):
        limit = len(self.items) * 4 + 64
        if len(self.recent_heap) <= limit and len(self.hot_heap) <= limit:
            return
        self.recent_heap = []
        self.hot_heap = []
        for key, item in self.items.items():
            self._touch(key, item)

    def _oldest_recent(self):
        while self.recent_heap:
            last, version, key = heappop(self.recent_heap)
            item = self.items.get(key)
            if item is not None and item[3] == "r" and item[2] == last and item[4] == version:
                return key
        return None

    def _weakest_hot(self):
        while self.hot_heap:
            frequency, negative_size, last, version, key = heappop(self.hot_heap)
            item = self.items.get(key)
            if (item is not None and item[3] == "h" and item[1] == frequency
                    and item[0] == -negative_size and item[2] == last and item[4] == version):
                return key
        return None

    def _victim(self):
        if self.recent_bytes > self.target_recent:
            key = self._oldest_recent()
            if key is not None:
                return key
            return self._weakest_hot()
        key = self._weakest_hot()
        if key is not None:
            return key
        return self._oldest_recent()

    def access(self, key: int, size: int, now: int) -> list[int]:
        if not isinstance(key, int) or isinstance(key, bool):
            return []
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            return []

        self.tick += 1
        if self.tick % self.decay_period == 0:
            self._decay()

        item = self.items.get(key)
        if item is not None:
            item[2] = self.tick
            if item[3] == "r":
                item[1] = min(16, item[1] + 1)
                if item[1] >= 2:
                    item[3] = "h"
                    self.recent_bytes -= item[0]
            self._touch(key, item)
            self._maybe_rebuild()
            return []

        ghost = self.ghosts.pop(key, None)
        if ghost is not None and self.capacity_bytes:
            step = max(1, self.capacity_bytes // 16)
            if ghost[0] == "r":
                self.target_recent = min(self.capacity_bytes, self.target_recent + step)
            else:
                self.target_recent = max(0, self.target_recent - step)

        if self.capacity_bytes == 0 or size > self.capacity_bytes:
            self._maybe_rebuild()
            return []

        evicted = []
        while self.used_bytes + size > self.capacity_bytes:
            victim = self._victim()
            if victim is None:
                break
            old = self.items.pop(victim)
            self.used_bytes -= old[0]
            if old[3] == "r":
                self.recent_bytes -= old[0]
            self._remember(victim, old[3])
            evicted.append(victim)

        segment = "h" if ghost is not None else "r"
        frequency = 2 if segment == "h" else 1
        item = [size, frequency, self.tick, segment, 0]
        self.items[key] = item
        self.used_bytes += size
        if segment == "r":
            self.recent_bytes += size
        self._touch(key, item)
        self._maybe_rebuild()
        return evicted
