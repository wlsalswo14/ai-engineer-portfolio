from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, capacity_bytes)
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        self.t1_bytes = 0
        self.t2_bytes = 0
        self.b1_bytes = 0
        self.b2_bytes = 0
        self.target_bytes = 0

    def _remove_ghost(self, key):
        if key in self.b1:
            self.b1_bytes -= self.b1.pop(key)
            return True
        if key in self.b2:
            self.b2_bytes -= self.b2.pop(key)
            return True
        return False

    def _add_ghost(self, key, size, frequent):
        self._remove_ghost(key)
        if size <= 0 or self.capacity_bytes == 0:
            return
        if frequent:
            self.b2[key] = size
            self.b2_bytes += size
        else:
            self.b1[key] = size
            self.b1_bytes += size
        while self.b1_bytes + self.b2_bytes > self.capacity_bytes:
            if self.b1:
                _, old_size = self.b1.popitem(last=False)
                self.b1_bytes -= old_size
            elif self.b2:
                _, old_size = self.b2.popitem(last=False)
                self.b2_bytes -= old_size
            else:
                break

    def _replace(self, incoming_in_b2):
        if not self.t1 and not self.t2:
            return None
        if self.t1 and (
            self.t1_bytes > self.target_bytes
            or (incoming_in_b2 and self.t1_bytes == self.target_bytes)
        ):
            old_key, old_size = self.t1.popitem(last=False)
            self.t1_bytes -= old_size
            self._add_ghost(old_key, old_size, False)
            return old_key
        if self.t2:
            old_key, old_size = self.t2.popitem(last=False)
            self.t2_bytes -= old_size
            self._add_ghost(old_key, old_size, True)
            return old_key
        old_key, old_size = self.t1.popitem(last=False)
        self.t1_bytes -= old_size
        self._add_ghost(old_key, old_size, False)
        return old_key

    def _make_room(self, size, incoming_in_b2, evicted):
        while self.t1_bytes + self.t2_bytes + size > self.capacity_bytes:
            old_key = self._replace(incoming_in_b2)
            if old_key is None:
                break
            evicted.append(old_key)

    def access(self, key: int, size: int, now: int) -> list[int]:
        size = max(0, size)

        if key in self.t1:
            stored_size = self.t1.pop(key)
            self.t1_bytes -= stored_size
            self.t2[key] = stored_size
            self.t2_bytes += stored_size
            return []

        if key in self.t2:
            stored_size = self.t2.pop(key)
            self.t2[key] = stored_size
            return []

        in_b1 = key in self.b1
        in_b2 = key in self.b2

        if size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        if in_b1:
            ratio = self.b2_bytes // max(1, self.b1_bytes)
            self.target_bytes = min(
                self.capacity_bytes,
                self.target_bytes + max(1, ratio),
            )
            self._remove_ghost(key)
        elif in_b2:
            ratio = self.b1_bytes // max(1, self.b2_bytes)
            self.target_bytes = max(
                0,
                self.target_bytes - max(1, ratio),
            )
            self._remove_ghost(key)

        evicted = []
        self._make_room(size, in_b2, evicted)

        if in_b1 or in_b2:
            self.t2[key] = size
            self.t2_bytes += size
        else:
            self.t1[key] = size
            self.t1_bytes += size

        return evicted
