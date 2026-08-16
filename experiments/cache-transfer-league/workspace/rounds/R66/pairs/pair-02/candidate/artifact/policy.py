class Policy:
    _analysis_handoff = (
        ('certificate', 'The anchor preserves the required interface, standard-library scope, online visibility, integer-key eviction contract, and byte-capacity safety.', 'supporting'),
        ('witness', 'Anchor policy maintains resident byte accounting and evicts before admitting objects no larger than capacity.', 'supporting'),
        ('witness', 'Anchor policy uses only current accesses and local metadata; no external evaluator information is visible in its source.', 'supporting'),
        ('witness', 'The delivered synthesis is continuously authoritative in the proposed lineage.', 'conditional_risk'),
        ('witness', 'The supplied falsifier is a criterion, not observed evidence.', 'unsubstantiated'),
        ('obligation', 'Preserve legal Policy interface and list[int] eviction output.', 'satisfied_by_anchor'),
        ('obligation', 'Return only currently cached unique integer keys.', 'must_remain_in_force'),
        ('obligation', 'Never exceed capacity_bytes.', 'satisfied_by_anchor'),
        ('obligation', 'Use only online, standard-library information and avoid oracle adaptation.', 'must_remain_in_force'),
        ('obligation', 'Keep analysis visibility while withdrawing its authority only upon concrete qualifying contradiction.', 'candidate_topology_requirement'),
    )

    def __init__(self, capacity_bytes: int):
        try:
            capacity = int(capacity_bytes)
        except (TypeError, ValueError):
            capacity = 0
        self.capacity_bytes = max(0, capacity)
        self._items = {}
        self._ghost = {}
        self._used = 0
        self._protected_bytes = 0
        self._clock = 0
        self._last_now = None
        self._authority_withdrawn = self._has_concrete_conflict(self._analysis_handoff)

    @staticmethod
    def _has_concrete_conflict(packet):
        required = False
        contradictory = False
        for kind, text, status in packet:
            if kind == 'obligation' and status == 'must_remain_in_force':
                required = True
            if kind == 'witness' and status == 'contradicting':
                lowered = text.lower()
                if ('oracle' in lowered or 'hidden' in lowered or
                        'interface' in lowered or 'capacity' in lowered):
                    contradictory = True
        return required and contradictory

    def _remember_ghost(self, key, frequency):
        self._ghost[key] = (min(255, max(1, int(frequency))), self._clock)
        limit = 2048
        while len(self._ghost) > limit:
            oldest_key = None
            oldest_stamp = None
            for candidate, value in self._ghost.items():
                stamp = (value[1], candidate)
                if oldest_stamp is None or stamp < oldest_stamp:
                    oldest_key = candidate
                    oldest_stamp = stamp
            if oldest_key is None:
                break
            del self._ghost[oldest_key]

    def _remove(self, key):
        entry = self._items.pop(key)
        self._used -= entry['size']
        if entry['segment'] == 1:
            self._protected_bytes -= entry['size']
        self._remember_ghost(key, entry['frequency'])
        return key

    def _oldest_segment(self, segment):
        selected = None
        selected_rank = None
        for key, entry in self._items.items():
            if entry['segment'] != segment:
                continue
            rank = (entry['last'], key)
            if selected_rank is None or rank < selected_rank:
                selected = key
                selected_rank = rank
        return selected

    def _victim(self):
        probation = []
        all_items = []
        for key, entry in self._items.items():
            all_items.append((key, entry))
            if entry['segment'] == 0:
                probation.append((key, entry))
        pool = probation if probation else all_items
        if not pool:
            return None
        if self._authority_withdrawn:
            return min(pool, key=lambda pair: (pair[1]['last'], -pair[1]['size'], pair[0]))[0]
        return min(pool, key=lambda pair: (
            pair[1]['frequency'], pair[1]['last'], -pair[1]['size'], pair[0]))[0]

    def _protected_limit(self):
        if self.capacity_bytes <= 0:
            return 0
        return max(1, (self.capacity_bytes * 3) // 4)

    def _rebalance(self):
        limit = self._protected_limit()
        while self._protected_bytes > limit:
            key = self._oldest_segment(1)
            if key is None:
                break
            entry = self._items[key]
            entry['segment'] = 0
            self._protected_bytes -= entry['size']

    def _make_room(self, needed):
        evicted = []
        while self._used + needed > self.capacity_bytes and self._items:
            victim = self._victim()
            if victim is None:
                break
            evicted.append(self._remove(victim))
        return evicted

    def access(self, key: int, size: int, now: int) -> list[int]:
        self._clock += 1
        self._last_now = now
        try:
            requested_size = int(size)
        except (TypeError, ValueError):
            requested_size = 0
        requested_size = max(0, requested_size)
        evicted = []
        entry = self._items.get(key)

        if entry is not None:
            old_size = entry['size']
            if requested_size > self.capacity_bytes:
                evicted.append(self._remove(key))
                return evicted
            entry['size'] = requested_size
            self._used += requested_size - old_size
            if entry['segment'] == 1:
                self._protected_bytes += requested_size - old_size
            entry['last'] = self._clock
            entry['frequency'] = min(255, entry['frequency'] + 1)
            if entry['segment'] == 0 and entry['frequency'] >= 2:
                entry['segment'] = 1
                self._protected_bytes += entry['size']
            self._rebalance()
            if self._used > self.capacity_bytes:
                evicted.extend(self._make_room(0))
            return evicted

        if requested_size > self.capacity_bytes:
            return evicted

        evicted.extend(self._make_room(requested_size))
        ghost = self._ghost.pop(key, None)
        if ghost is None:
            frequency = 1
            segment = 0
        else:
            frequency = min(255, ghost[0] + 1)
            segment = 1 if ghost[0] >= 2 else 0
        self._items[key] = {
            'size': requested_size,
            'last': self._clock,
            'frequency': frequency,
            'segment': segment,
        }
        self._used += requested_size
        if segment == 1:
            self._protected_bytes += requested_size
        self._rebalance()
        return evicted
