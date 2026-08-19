# Chess domain contract

Produce one complete standard-library-only `engine.py` that implements legal chess and UCI. It must answer every `go movetime` with a legal move before the deadline. Public development uses a frozen 50-opening set against an opponent below the hidden certification tier. Certification uses a different frozen 50-opening set with zero overlapping starting FENs. The certification opponent, openings, results, and numeric scores are never shown to the architect or inner loop.
