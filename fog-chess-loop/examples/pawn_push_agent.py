#!/usr/bin/env python3
from __future__ import annotations

import json
import sys


for line in sys.stdin:
    obs = json.loads(line)
    if obs.get("side") == "black":
        print("e7e5", flush=True)
    else:
        print("e2e4", flush=True)
