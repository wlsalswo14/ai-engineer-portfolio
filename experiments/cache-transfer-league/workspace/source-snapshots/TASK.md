# Candidate Task: Cache Policy

Write `policy.py` using only the Python standard library.

```python
class Policy:
    def __init__(self, capacity_bytes: int):
        ...

    def access(self, key: int, size: int, now: int) -> list[int]:
        """
        Process one object request and return the keys evicted by this request.
        """
```

The evaluator owns the authoritative cache state. Your policy should return only
keys that are currently cached and should never exceed `capacity_bytes`.

Optimize for:

- object hit rate;
- byte hit rate;
- scan resistance;
- phase-shift adaptation;
- regret against an offline optimum.

Do not copy, import, invoke, inspect, or adapt evaluator-side reference
implementations, hidden traces, oracle decisions, benchmark source paths, or
external cache libraries. Do not use networking, subprocesses, or non-stdlib
packages.
