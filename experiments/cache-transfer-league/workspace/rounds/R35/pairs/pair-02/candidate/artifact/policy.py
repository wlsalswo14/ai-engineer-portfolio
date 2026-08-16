from collections import OrderedDict

# Provenance accountability record carried unchanged from the preconstruction charter.
PROVENANCE = {
    'certificate': 'Preconstruction charter: distinguish anchor-inherited heuristics from contract-grounded obligations and candidate claims; preserve unresolved tensions for accountable materialization without issuing policy source.',
    'witnesses': (
        ('anchor-derived', 'Two recency segments, ghost histories, and adaptive protected sizing are assumed useful for scan resistance and phase-shift adaptation.', 'unvalidated_without_scores'),
        ('anchor-derived', 'Oversized, nonpositive, or zero-capacity requests are treated as nonresident.', 'behavioral_assumption'),
        ('contract-grounded', 'The evaluator owns authoritative state; returned evictions must be unique integer keys that are currently cached.', 'binding_obligation'),
        ('contract-grounded', 'Online processing, standard-library-only implementation, capacity safety, and no oracle or benchmark leakage are mandatory.', 'binding_obligation'),
        ('candidate-hypothesis', 'Visible provenance should enable downstream challenge of inherited assumptions while preserving one executable lineage.', 'testable_claim'),
    ),
    'obligations': (
        ('interface_legality', 'Honor the specified constructor and access signatures and return a list of integer keys.'),
        ('capacity_safety', 'Never cause resident bytes to exceed capacity_bytes, including after insertion and eviction.'),
        ('eviction_validity', 'Return only currently cached, unique keys evicted by the current request.'),
        ('online_visibility', 'Use only current and prior online observations plus declared construction evidence.'),
        ('provenance_accountability', 'Keep each inherited heuristic, contract commitment, and unresolved tension attributable through materialization and release.'),
        ('constraint_compliance', 'Use only the Python standard library and avoid reference implementations, hidden traces, benchmark paths, networking, subprocesses, and external packages.'),
    ),
    'exact_actions': (
        'Carry this charter and its origin labels into materialization unchanged.',
        'Resolve each unresolved anchor assumption against the binding obligations before executable completion.',
        'Explicitly verify hit behavior, size handling, eviction validity, uniqueness, and byte accounting.',
        'Preserve a visible record of any assumption retained, modified, or rejected and its reason.',
        'Pass the complete executable state together with this provenance record to final release for contract reconciliation.',
    ),
}

# Materialization record: retain the two recency segments and ghost histories;
# modify protected sizing adaptively; reject all non-online and non-stdlib inputs.
class Policy:
    def __init__(self, capacity_bytes: int):
        try:
            capacity = int(capacity_bytes)
        except (TypeError, ValueError, OverflowError):
            capacity = 0
        self._capacity = max(0, capacity)
        self._probation = OrderedDict()
        self._protected = OrderedDict()
        self._ghost_probation = OrderedDict()
        self._ghost_protected = OrderedDict()
        self._probation_bytes = 0
        self._protected_bytes = 0
        self._resident_bytes = 0
        self._protected_target = self._capacity // 2
        self._ghost_limit = 4096

    def _forget_history(self, key):
        self._ghost_probation.pop(key, None)
        self._ghost_protected.pop(key, None)

    def _remember(self, table, other, key, size):
        other.pop(key, None)
        table.pop(key, None)
        table[key] = size
        while len(table) > self._ghost_limit:
            table.popitem(last=False)

    def _make_room(self, required, evicted):
        while self._resident_bytes + required > self._capacity:
            if self._probation:
                key, size = self._probation.popitem(last=False)
                self._probation_bytes -= size
                self._resident_bytes -= size
                self._remember(self._ghost_probation, self._ghost_protected, key, size)
                evicted.append(key)
            elif self._protected:
                key, size = self._protected.popitem(last=False)
                self._protected_bytes -= size
                self._resident_bytes -= size
                self._remember(self._ghost_protected, self._ghost_probation, key, size)
                evicted.append(key)
            else:
                break

    def _rebalance(self):
        while self._protected and self._protected_bytes > self._protected_target:
            key, size = self._protected.popitem(last=False)
            self._protected_bytes -= size
            self._probation[key] = size
            self._probation_bytes += size

    def _insert_probation(self, key, size):
        self._forget_history(key)
        self._probation[key] = size
        self._probation_bytes += size
        self._resident_bytes += size

    def _insert_protected(self, key, size):
        self._forget_history(key)
        self._protected[key] = size
        self._protected_bytes += size
        self._resident_bytes += size

    def access(self, key: int, size: int, now: int) -> list[int]:
        del now
        evicted = []
        try:
            requested = int(size)
        except (TypeError, ValueError, OverflowError):
            requested = 0

        in_probation = key in self._probation
        in_protected = key in self._protected
        if in_probation or in_protected:
            if in_probation:
                old_size = self._probation.pop(key)
                self._probation_bytes -= old_size
            else:
                old_size = self._protected.pop(key)
                self._protected_bytes -= old_size
            self._resident_bytes -= old_size
            self._forget_history(key)

            if requested <= 0 or requested > self._capacity:
                evicted.append(key)
                return evicted

            self._make_room(requested, evicted)
            if in_protected:
                self._insert_protected(key, requested)
            else:
                self._insert_protected(key, requested)
            self._rebalance()
            return evicted

        if requested <= 0 or self._capacity <= 0 or requested > self._capacity:
            return evicted

        if key in self._ghost_probation:
            self._ghost_probation.pop(key, None)
            step = max(1, self._capacity // 16)
            self._protected_target = min(self._capacity, self._protected_target + step)
            destination = self._protected
        elif key in self._ghost_protected:
            self._ghost_protected.pop(key, None)
            step = max(1, self._capacity // 16)
            self._protected_target = max(0, self._protected_target - step)
            destination = self._protected
        else:
            destination = self._probation

        self._make_room(requested, evicted)
        if destination is self._protected:
            self._insert_protected(key, requested)
            self._rebalance()
        else:
            self._insert_probation(key, requested)
        return evicted
