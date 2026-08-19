from collections import OrderedDict


class Policy:
    def __init__(self, capacity_bytes: int):
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.probation = OrderedDict()
        self.protected = OrderedDict()
        self.protected_bytes = 0
        self.used_bytes = 0
        self.frequency = {}
        self.operations = 0

    def _note(self, key):
        self.operations += 1
        self.frequency[key] = min(15, self.frequency.get(key, 0) + 1)
        if self.operations >= 256:
            self.operations = 0
            for existing in tuple(self.frequency):
                value = self.frequency[existing] >> 1
                if value:
                    self.frequency[existing] = value
                elif existing in self.probation or existing in self.protected:
                    self.frequency[existing] = 1
                else:
                    del self.frequency[existing]

    def _demote_protected(self):
        target = self.capacity_bytes // 2
        while self.protected and self.protected_bytes > target:
            key, size = self.protected.popitem(last=False)
            self.protected_bytes -= size
            self.probation[key] = size
            self.probation.move_to_end(key, last=False)

    def _ordered_victims(self, segment):
        positions = {key: index for index, key in enumerate(segment)}
        return sorted(
            segment,
            key=lambda key: (self.frequency.get(key, 1), positions[key]),
        )

    def _eviction_plan(self, incoming_size):
        required = self.used_bytes + incoming_size - self.capacity_bytes
        if required <= 0:
            return []

        plan = []
        freed = 0
        for segment in (self.probation, self.protected):
            for key in self._ordered_victims(segment):
                plan.append(key)
                freed += segment[key]
                if freed >= required:
                    return plan
        return None

    def _apply_evictions(self, plan):
        evicted = []
        for key in plan:
            if key in self.probation:
                size = self.probation.pop(key)
            elif key in self.protected:
                size = self.protected.pop(key)
                self.protected_bytes -= size
            else:
                continue
            self.used_bytes -= size
            evicted.append(key)
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        del now
        self._note(key)

        if key in self.protected:
            stored_size = self.protected.pop(key)
            self.protected[key] = stored_size
            return []

        if key in self.probation:
            stored_size = self.probation.pop(key)
            self.protected[key] = stored_size
            self.protected_bytes += stored_size
            self._demote_protected()
            return []

        incoming_size = max(0, int(size))
        if incoming_size > self.capacity_bytes or self.capacity_bytes == 0:
            return []

        plan = self._eviction_plan(incoming_size)
        if plan is None:
            return []

        candidate_frequency = self.frequency.get(key, 1)
        if any(
            self.frequency.get(victim, 1) > candidate_frequency
            for victim in plan
        ):
            return []

        evicted = self._apply_evictions(plan)
        self.probation[key] = incoming_size
        self.used_bytes += incoming_size
        return evicted
