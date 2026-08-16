#!/usr/bin/env python3
"""scorer_bench_meta r11 — calibrated nontrivial task ladder.

Round-10 Composer feedback (verbatim, key parts):

  "다섯 번째 연속 calibration 실패다. 다음 라운드 핵심 과제는 단 하나,
   'calibrated nontrivial task ladder + live Opus 비교'를 실제로 굴려서
   증거를 만드는 것이다.

   1. Task 설계: Opus 4.7 one_shot pass rate가 0이 아니라 0.1~0.5 구간에
      떨어지는 코딩 과제 3~5개를 새로 짜라.
   2. Calibration probe를 먼저 돌려서 saturate된 task는 ladder에서 빼라.
   3. live --compare-baseline을 candidate / r133 / r38 / one_shot / ablation
      에 대해 같은 task·같은 budget·같은 종결조건으로 실제 Opus로 돌려라.
   4. 우월성 주장은 정확도/시간/비용/견고함 중 최소 한 축에서 r133·r38보다
      명시적으로 더 낫다는 수치 증거를 동반해야 한다.
   5. Harness/anti-cheat/self-test 품질은 유지하되, 그것을 우월성 증거로
      포장하지 마라.
   6. private scorer를 다시 만드는 방향으로 회귀하지 마라."

What r11 changes from r10:

  1. FOUR new tasks chosen for higher one-shot difficulty:

       - taskA `semver_compare`        — full SemVer 2.0.0 ordering with
                                          strict validation (leading zeros,
                                          numeric vs string prerelease,
                                          "no-prerelease > prerelease" rule,
                                          build metadata ignored for
                                          ordering).
       - taskB `cidr_v4_coalesce`      — IPv4 CIDR coalescing: recursive
                                          merging, host-bit normalization,
                                          strict validation.  No
                                          `ipaddress` module allowed.
       - taskC `glob_match`            — POSIX-like glob with `**`,
                                          `[!abc]` (NOT `[^abc]`),
                                          backslash escapes, hidden-file
                                          rule.  No `fnmatch` allowed.
       - taskD `roman_numeral_strict`  — strict Roman numeral parse +
                                          render for 1..3999; rejects
                                          IIII, IIV, VV, IL, etc.

     Each task has many edge cases that are easy to miss in one-shot
     synthesis but tractable to fix with concrete counterexamples.

  2. The probe + verdict + ablation + anti-cheat machinery is preserved
     from r10 verbatim.  Only the task definitions and CLI defaults
     change; the rest is the proven harness from r9/r10.

  3. Default `--probe-pass-threshold` raised to 0.50 per Composer's r10
     guidance (Opus 4.7 pass rate in 0.1-0.5 band counts as
     calibrated).  Tasks whose probe one-shot rate >= 0.5 are dropped.

  4. Self-test runs >= 130 offline checks before any LLM call.  This
     is wiring evidence, NOT verdict evidence.

Honest disclosure:

  These task families were chosen because each has many subtle edge
  cases well-documented in the wider literature (semver.org spec,
  RFC 4632 for CIDR, POSIX 1003.1 / fnmatch semantics for glob,
  classical strict-Roman validation rules).  The hypothesis is that
  Opus 4.7 + --effort low will get the obvious cases right but miss
  several subtle ones in one-shot, falling into the 0.1-0.5
  calibrated band.  The probe measures this empirically.  If a task
  still saturates at >=0.5 one-shot pass rate with 2 seeds, it is
  dropped from the ladder before the live compare so budget is not
  wasted.

  Tasks that survive the probe are run through 5 policies on 3 seeds
  with the same caps.  Strict superiority is declared only if the
  candidate beats BOTH r133 AND r38 on >=1 axis on every probe-passing
  task, AND the counterexample-feedback ablation shows improvement.

  The harness/anti-cheat/self-test quality is reported as wiring
  evidence only.  It is NOT presented as proof of superiority.
"""
from __future__ import annotations

import argparse
import io
import json
import hashlib
import math
import os
import random
import re
import statistics
import subprocess
import sys
import textwrap
import time
import traceback
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def pretty_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pretty_json(value) + "\n", encoding="utf-8")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stdev_or_zero(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    return statistics.pstdev(xs)


# ---------------------------------------------------------------------------
# Core dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TestCase:
    name: str
    feature: str
    payload: dict
    expected_kind: str          # 'value' or 'error'
    expected_value: Any | None = None
    expected_error: str | None = None
    input_repr: str = ""

    def as_jsonable(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "feature": self.feature,
            "payload": self.payload,
            "expected_kind": self.expected_kind,
            "expected_value": self.expected_value,
            "expected_error": self.expected_error,
            "input_repr": self.input_repr,
        }


@dataclass
class Goal:
    task_name: str
    seed: int
    bare_text: str
    cases: list[TestCase]
    features: list[str]


@dataclass
class ScorerRun:
    passed: bool
    score: float
    passed_cases: int
    total_cases: int
    failed: list[dict[str, Any]] = field(default_factory=list)
    failed_features: list[str] = field(default_factory=list)
    runner_error: str | None = None
    static_rejected: bool = False


@dataclass
class ActorResult:
    source: str
    raw_response: str
    prompt_sha256: str
    response_sha256: str
    cost_usd: float = 0.0
    duration_ms: int = 0
    model: str = ""
    error: str | None = None


# ===========================================================================
# TASK A — semver_compare
# ===========================================================================


TASK_A_BARE_GOAL = textwrap.dedent('''\
    Implement a Python module `solution.py` that defines exactly one
    public function:

        def compare(a: str, b: str) -> int:
            """Compare two version strings per Semantic Versioning 2.0.0
            (https://semver.org/spec/v2.0.0.html).

            Return -1 if a < b, 0 if a == b, 1 if a > b.

            Both arguments must be valid SemVer 2.0.0 strings.  On any
            invalid input, raise ValueError("invalid_version").

            VALIDATION (apply to BOTH a and b before comparing):
              The grammar is:
                  MAJOR "." MINOR "." PATCH ["-" PRE] ["+" BUILD]
              Where:
                - MAJOR, MINOR, PATCH are non-negative decimal integers
                  with NO leading zeros.  "0" is allowed but "01" is not.
                - PRE is a dot-separated, non-empty sequence of identifiers.
                  Each identifier is non-empty and matches [0-9A-Za-z-]+.
                  Numeric identifiers (only digits) MUST NOT have leading
                  zeros: "01" as a prerelease identifier is invalid; "0"
                  alone is allowed.
                - BUILD is a dot-separated, non-empty sequence of
                  identifiers.  Each identifier is non-empty and matches
                  [0-9A-Za-z-]+.  Build identifiers MAY have leading zeros
                  (build metadata is opaque).
                - The string must contain no extra whitespace anywhere.
                - Strings like "1.0", "1.0.0.0", "1.0.0-", "1.0.0+",
                  "1.0.0-+", "1.0.0-rc..1", " 1.0.0", "1.0.0 ", or
                  empty string are all invalid.

            COMPARISON RULES:
              1. Compare MAJOR, MINOR, PATCH numerically in that order.
              2. If those are equal:
                   - If both versions have NO prerelease tag, they are
                     equal in precedence.
                   - If exactly one has a prerelease tag, the one
                     WITHOUT the prerelease tag has HIGHER precedence.
                     (i.e. 1.0.0 > 1.0.0-rc.1)
                   - If both have prerelease tags, compare them
                     identifier by identifier from left to right:
                       * If identifier i is missing on one side and
                         present on the other, the side with MORE
                         identifiers has HIGHER precedence (so
                         1.0.0-alpha < 1.0.0-alpha.1).
                       * If both identifiers are numeric, compare them
                         numerically.
                       * If both identifiers are non-numeric, compare
                         them lexicographically by ASCII code.
                       * If types differ, the numeric identifier has
                         LOWER precedence than the non-numeric.
              3. Build metadata MUST be IGNORED for ordering, but
                 syntactically validated (so "1.0.0+abc" and
                 "1.0.0+xyz" compare equal).

            Examples:
              compare("1.0.0", "2.0.0")               # -1
              compare("2.0.0", "2.1.0")               # -1
              compare("2.1.0", "2.1.1")               # -1
              compare("1.0.0", "1.0.0")               # 0
              compare("1.0.0+a", "1.0.0+b")           # 0  (build ignored)
              compare("1.0.0-rc.1", "1.0.0")          # -1 (rel > pre)
              compare("1.0.0-alpha", "1.0.0-alpha.1") # -1 (longer wins when prefix matches)
              compare("1.0.0-alpha.1", "1.0.0-alpha.beta")  # -1 (numeric < non-numeric)
              compare("1.0.0-alpha.10", "1.0.0-alpha.2")    #  1 (numeric: 10 > 2)
              compare("1.0.0-rc.11", "1.0.0-rc.2")    #  1 (numeric)
              compare("1.0.0-beta", "1.0.0-rc")       # -1 (lex: 'b' < 'r')

              compare("01.0.0", "1.0.0")              # raises ValueError("invalid_version")
              compare("1.0.0-rc.01", "1.0.0")         # raises (numeric pre with leading zero)
              compare("1.0.0-rc..1", "1.0.0")         # raises (empty identifier)
              compare("1.0.0", "1.0")                 # raises (missing patch)
              compare("1.0.0-", "1.0.0")              # raises (empty pre)
              compare("1.0.0+", "1.0.0")              # raises (empty build)
              compare("", "1.0.0")                    # raises (empty)
              compare(" 1.0.0", "1.0.0")              # raises (whitespace)
              compare("1.0.0", 1)                     # raises (non-string -> ValueError)

            DO NOT import `semver`, `packaging`, or any third-party
            module.  Use only the Python standard library.  Do NOT
            access os.environ, subprocess, network, or filesystem.

            Return ONLY {"code": <complete solution.py source>}.
            """
''')


def _ref_parse_semver(s: Any) -> tuple[tuple[int, int, int], list[Any] | None, str | None]:
    """Reference parser; raises ValueError on invalid."""
    if not isinstance(s, str):
        raise ValueError("invalid_version")
    if s == "" or any(c.isspace() for c in s):
        raise ValueError("invalid_version")
    plus_idx = s.find("+")
    if plus_idx >= 0:
        head, build = s[:plus_idx], s[plus_idx + 1:]
        if build == "":
            raise ValueError("invalid_version")
        if "+" in build:
            raise ValueError("invalid_version")
        for ident in build.split("."):
            if not ident or not re.fullmatch(r"[0-9A-Za-z-]+", ident):
                raise ValueError("invalid_version")
    else:
        head, build = s, None
    dash_idx = head.find("-")
    if dash_idx >= 0:
        core, pre = head[:dash_idx], head[dash_idx + 1:]
        if pre == "":
            raise ValueError("invalid_version")
        pre_ids: list[Any] = []
        for ident in pre.split("."):
            if not ident or not re.fullmatch(r"[0-9A-Za-z-]+", ident):
                raise ValueError("invalid_version")
            if ident.isdigit():
                if len(ident) > 1 and ident[0] == "0":
                    raise ValueError("invalid_version")
                pre_ids.append(("num", int(ident)))
            else:
                pre_ids.append(("str", ident))
    else:
        core, pre_ids = head, None
    parts = core.split(".")
    if len(parts) != 3:
        raise ValueError("invalid_version")
    nums = []
    for p in parts:
        if not p or not p.isdigit():
            raise ValueError("invalid_version")
        if len(p) > 1 and p[0] == "0":
            raise ValueError("invalid_version")
        nums.append(int(p))
    return ((nums[0], nums[1], nums[2]), pre_ids, build)


def _ref_compare_pre(a_ids: list[Any], b_ids: list[Any]) -> int:
    n = min(len(a_ids), len(b_ids))
    for i in range(n):
        ak, av = a_ids[i]
        bk, bv = b_ids[i]
        if ak == "num" and bk == "num":
            if av < bv:
                return -1
            if av > bv:
                return 1
        elif ak == "str" and bk == "str":
            if av < bv:
                return -1
            if av > bv:
                return 1
        else:
            return -1 if ak == "num" else 1
    if len(a_ids) < len(b_ids):
        return -1
    if len(a_ids) > len(b_ids):
        return 1
    return 0


def _ref_semver_compare(a: str, b: str) -> int:
    am, ap, _ = _ref_parse_semver(a)
    bm, bp, _ = _ref_parse_semver(b)
    if am != bm:
        return -1 if am < bm else 1
    if ap is None and bp is None:
        return 0
    if ap is None:
        return 1
    if bp is None:
        return -1
    return _ref_compare_pre(ap, bp)


def _gen_taskA_cases(seed: int) -> list[TestCase]:
    rng = random.Random(seed * 7919 + 11)
    cases: list[TestCase] = []

    def case(name, feat, a, b, expected, repr_=""):
        if isinstance(expected, int) and not isinstance(expected, bool):
            cases.append(TestCase(name, feat, {"a": a, "b": b}, "value",
                                   expected_value=expected, input_repr=repr_))
        else:
            cases.append(TestCase(name, feat, {"a": a, "b": b}, "error",
                                   expected_error=expected[1], input_repr=repr_))

    case("simple_major_lt", "major_compare", "1.0.0", "2.0.0", -1, "1<2")
    case("simple_major_gt", "major_compare", "3.0.0", "2.0.0", 1, "3>2")
    case("simple_major_eq", "major_compare", "5.0.0", "5.0.0", 0, "5==5")
    case("simple_minor_lt", "minor_compare", "2.0.0", "2.1.0", -1, "2.0<2.1")
    case("simple_minor_gt", "minor_compare", "2.5.0", "2.1.0", 1, "2.5>2.1")
    case("simple_patch_lt", "patch_compare", "2.1.0", "2.1.1", -1, "patch")
    case("zero_versions_eq", "zero_versions", "0.0.0", "0.0.0", 0, "all zero")
    case("large_numbers", "large_numbers", "100.200.300", "100.200.301", -1,
         "large patch")
    case("multi_digit_minor", "multi_digit", "1.10.0", "1.9.0", 1, "10>9 minor")
    case("multi_digit_patch", "multi_digit", "1.0.10", "1.0.9", 1, "10>9 patch")

    case("rel_gt_pre", "release_vs_pre", "1.0.0", "1.0.0-rc.1", 1, "rel > pre")
    case("pre_lt_rel", "release_vs_pre", "1.0.0-rc.1", "1.0.0", -1, "pre < rel")
    case("alpha_vs_alpha1", "pre_longer_wins",
         "1.0.0-alpha", "1.0.0-alpha.1", -1, "longer wins")
    case("alpha1_vs_alpha", "pre_longer_wins",
         "1.0.0-alpha.1", "1.0.0-alpha", 1, "longer wins")
    case("numeric_lt_string", "numeric_vs_string",
         "1.0.0-alpha.1", "1.0.0-alpha.beta", -1, "1 < beta (num<str)")
    case("string_gt_numeric", "numeric_vs_string",
         "1.0.0-alpha.beta", "1.0.0-alpha.1", 1, "beta > 1 (str>num)")
    case("numeric_10_gt_2", "numeric_compare",
         "1.0.0-alpha.10", "1.0.0-alpha.2", 1, "10 > 2 numerically")
    case("numeric_11_gt_2_rc", "numeric_compare",
         "1.0.0-rc.11", "1.0.0-rc.2", 1, "rc.11 > rc.2")
    case("string_lex", "string_compare",
         "1.0.0-beta", "1.0.0-rc", -1, "beta < rc lex")
    case("alpha_eq", "pre_eq", "1.0.0-alpha", "1.0.0-alpha", 0, "equal pre")
    case("multi_id_pre", "multi_id_pre",
         "1.0.0-alpha.1.2", "1.0.0-alpha.1.3", -1, "third id")
    case("type_then_len", "pre_priority",
         "1.0.0-1", "1.0.0-1.1", -1, "len after equal nums")
    case("hyphen_in_id_compare", "hyphen_in_id",
         "1.0.0-x-yz", "1.0.0-x-yz.1", -1, "hyphen ids")

    case("build_ignored_eq", "build_ignored",
         "1.0.0+a", "1.0.0+b", 0, "build ignored")
    case("build_ignored_with_pre", "build_ignored",
         "1.0.0-rc+a", "1.0.0-rc+b", 0, "build ignored with pre")
    case("build_long", "build_ignored",
         "1.0.0+sha.abcd1234", "1.0.0+sha.efef9999", 0, "build ignored long")

    case("invalid_leading_zero_major", "leading_zero_major",
         "01.0.0", "1.0.0", ("error", "ValueError"), "01.x.x")
    case("invalid_leading_zero_minor", "leading_zero_minor",
         "1.01.0", "1.0.0", ("error", "ValueError"), "1.01.x")
    case("invalid_leading_zero_patch", "leading_zero_patch",
         "1.0.01", "1.0.0", ("error", "ValueError"), "1.x.01")
    case("invalid_leading_zero_pre_num", "leading_zero_pre",
         "1.0.0-rc.01", "1.0.0", ("error", "ValueError"), "rc.01")
    case("invalid_double_dot_pre", "empty_pre_id",
         "1.0.0-rc..1", "1.0.0", ("error", "ValueError"), "rc..1")
    case("invalid_missing_patch", "wrong_arity",
         "1.0", "1.0.0", ("error", "ValueError"), "missing patch")
    case("invalid_extra_part", "wrong_arity",
         "1.0.0.0", "1.0.0", ("error", "ValueError"), "extra part")
    case("invalid_empty_pre", "empty_pre",
         "1.0.0-", "1.0.0", ("error", "ValueError"), "empty pre")
    case("invalid_empty_build", "empty_build",
         "1.0.0+", "1.0.0", ("error", "ValueError"), "empty build")
    case("invalid_empty_string", "empty_input",
         "", "1.0.0", ("error", "ValueError"), "empty")
    case("invalid_leading_space", "whitespace",
         " 1.0.0", "1.0.0", ("error", "ValueError"), "leading space")
    case("invalid_trailing_space", "whitespace",
         "1.0.0 ", "1.0.0", ("error", "ValueError"), "trailing space")
    case("invalid_pre_with_at", "bad_id_chars",
         "1.0.0-rc@1", "1.0.0", ("error", "ValueError"), "@ in pre")
    case("invalid_negative_major", "negative_number",
         "-1.0.0", "1.0.0", ("error", "ValueError"), "negative major")
    case("invalid_non_numeric_major", "non_numeric_core",
         "a.0.0", "1.0.0", ("error", "ValueError"), "non-numeric major")
    case("invalid_double_plus", "double_plus",
         "1.0.0++a", "1.0.0", ("error", "ValueError"), "++a build")
    case("invalid_non_string_b", "non_string",
         "1.0.0", 1, ("error", "ValueError"), "non-str b")
    case("zero_pre_id_ok", "zero_pre_id_ok",
         "1.0.0-0", "1.0.0-1", -1, "pre 0 < 1 numerically")

    seeds_strs = [
        "0.0.0", "1.0.0", "1.2.3", "10.20.30", "0.1.0",
        "1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta",
        "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1",
        "1.0.0-1", "1.0.0-1.2", "1.0.0+build", "1.0.0+abc.def",
        "2.0.0-rc.1+abc",
    ]
    for k in range(20):
        a = rng.choice(seeds_strs)
        b = rng.choice(seeds_strs)
        try:
            expected = _ref_semver_compare(a, b)
            case(f"rand_{k}", "randomized_compare", a, b, expected,
                 repr_=f"rand {a!r} vs {b!r}")
        except ValueError:
            continue

    return cases


def _features_taskA() -> list[str]:
    return sorted({
        "major_compare", "minor_compare", "patch_compare",
        "zero_versions", "large_numbers", "multi_digit",
        "release_vs_pre", "pre_longer_wins", "numeric_vs_string",
        "numeric_compare", "string_compare", "pre_eq",
        "multi_id_pre", "pre_priority", "hyphen_in_id",
        "build_ignored",
        "leading_zero_major", "leading_zero_minor", "leading_zero_patch",
        "leading_zero_pre", "empty_pre_id", "wrong_arity",
        "empty_pre", "empty_build", "empty_input", "whitespace",
        "bad_id_chars", "negative_number", "non_numeric_core",
        "double_plus", "non_string", "zero_pre_id_ok",
        "randomized_compare",
    })


_RUNNER_TASKA = textwrap.dedent("""\
    import json, sys, importlib.util
    SRC, CASES, OUT = sys.argv[1:4]
    spec = importlib.util.spec_from_file_location('solution', SRC)
    mod = importlib.util.module_from_spec(spec)
    runner_error = None
    try:
        sys.modules['solution'] = mod
        spec.loader.exec_module(mod)
    except Exception as exc:
        runner_error = "import_error:" + repr(exc)[:300]

    cases = json.load(open(CASES, encoding='utf-8'))
    results = []
    if runner_error is None:
        compare = getattr(mod, 'compare', None)
        if compare is None:
            runner_error = 'missing_function:compare'

    if runner_error is None:
        for case in cases:
            try:
                p = case['payload']
                got = compare(p['a'], p['b'])
                results.append({'got_kind': 'value', 'got_value': got,
                                'got_value_repr': repr(got)[:100]})
            except Exception as exc:
                results.append({'got_kind': 'error',
                                'got_error': type(exc).__name__,
                                'got_error_msg': str(exc)[:200]})

    json.dump({'runner_error': runner_error, 'results': results}, open(OUT, 'w'))
""").strip()


def _golden_taskA() -> str:
    return textwrap.dedent('''\
        import re

        _IDENT_RE = re.compile(r"[0-9A-Za-z-]+")

        def _parse(s):
            if not isinstance(s, str):
                raise ValueError("invalid_version")
            if s == "":
                raise ValueError("invalid_version")
            if any(c.isspace() for c in s):
                raise ValueError("invalid_version")
            plus = s.find("+")
            if plus >= 0:
                head, build = s[:plus], s[plus + 1:]
                if build == "" or "+" in build:
                    raise ValueError("invalid_version")
                for ident in build.split("."):
                    if not ident or not _IDENT_RE.fullmatch(ident):
                        raise ValueError("invalid_version")
            else:
                head = s
            dash = head.find("-")
            if dash >= 0:
                core, pre = head[:dash], head[dash + 1:]
                if pre == "":
                    raise ValueError("invalid_version")
                pre_ids = []
                for ident in pre.split("."):
                    if not ident or not _IDENT_RE.fullmatch(ident):
                        raise ValueError("invalid_version")
                    if ident.isdigit():
                        if len(ident) > 1 and ident[0] == "0":
                            raise ValueError("invalid_version")
                        pre_ids.append(("num", int(ident)))
                    else:
                        pre_ids.append(("str", ident))
            else:
                core = head
                pre_ids = None
            parts = core.split(".")
            if len(parts) != 3:
                raise ValueError("invalid_version")
            nums = []
            for p in parts:
                if not p or not p.isdigit():
                    raise ValueError("invalid_version")
                if len(p) > 1 and p[0] == "0":
                    raise ValueError("invalid_version")
                nums.append(int(p))
            return tuple(nums), pre_ids


        def _cmp_pre(a, b):
            n = min(len(a), len(b))
            for i in range(n):
                ak, av = a[i]
                bk, bv = b[i]
                if ak == "num" and bk == "num":
                    if av < bv:
                        return -1
                    if av > bv:
                        return 1
                elif ak == "str" and bk == "str":
                    if av < bv:
                        return -1
                    if av > bv:
                        return 1
                else:
                    return -1 if ak == "num" else 1
            if len(a) < len(b):
                return -1
            if len(a) > len(b):
                return 1
            return 0


        def compare(a, b):
            am, ap = _parse(a)
            bm, bp = _parse(b)
            if am != bm:
                return -1 if am < bm else 1
            if ap is None and bp is None:
                return 0
            if ap is None:
                return 1
            if bp is None:
                return -1
            return _cmp_pre(ap, bp)
    ''')


def _stub_taskA() -> str:
    """Wrong: simple lex compare; ignores all rules."""
    return textwrap.dedent('''\
        def compare(a, b):
            if a == b:
                return 0
            return -1 if a < b else 1
    ''')


# ===========================================================================
# TASK B — cidr_v4_coalesce
# ===========================================================================


TASK_B_BARE_GOAL = textwrap.dedent('''\
    Implement a Python module `solution.py` that defines exactly one
    public function:

        def coalesce(cidrs: list[str]) -> list[str]:
            """Coalesce a list of IPv4 CIDR strings into the minimum
            equivalent set, sorted by network address (numerically
            ascending).

            Returns a NEW list of canonical CIDR strings.  Does not
            mutate the input.

            VALIDATION:
              - Input must be a list (not tuple, not string).  If not,
                raise TypeError("not_a_list").
              - Each entry must be a string of the form "A.B.C.D/N":
                  * A,B,C,D are decimal integers in [0, 255] with NO
                    leading zeros (so "001.0.0.0/24" is invalid).
                  * N is a decimal integer in [0, 32] with NO leading
                    zeros (so "1.0.0.0/04" is invalid; "0" alone IS ok).
                  * Exactly one '/' separates the dotted-quad and prefix.
                  * No surrounding whitespace.
              - On any invalid entry, raise ValueError with message
                exactly "invalid_cidr:" + the offending string.

            NORMALIZATION:
              - Host bits (bits below the prefix boundary) MAY be set
                in the input but MUST be cleared in the output.  E.g.
                "192.168.1.5/24" is valid input that normalises to
                "192.168.1.0/24".
              - Output prefix is in canonical form: dotted-quad with
                no leading zeros + "/" + prefix length.

            COALESCING:
              - Identical (after normalisation) entries are deduplicated.
              - If A is a subset of B (i.e. all addresses in A lie in B),
                drop A and keep B.
              - If two adjacent /N networks share the same /N-1 supernet
                (i.e. one is the lower half and the other is the upper
                half), they merge into the /N-1 supernet.
              - Apply merging RECURSIVELY until no further merges occur.
              - The returned list is sorted by network address (the
                32-bit big-endian integer interpretation of the dotted
                quad), ascending.

            Edge cases:
              - Empty input -> empty list.
              - "0.0.0.0/0" covers everything; it absorbs all other
                entries (output is exactly ["0.0.0.0/0"]).
              - Adjacency without alignment does NOT merge.  For
                example "192.168.0.0/24" + "192.168.2.0/24" stays as
                two ranges (because the /23 supernet of 192.168.0.0/24
                would be 192.168.0.0/23, which does NOT include
                192.168.2.0/24).
              - "192.168.0.0/24" + "192.168.1.0/24" merges into
                "192.168.0.0/23".
              - Three ranges "192.168.0.0/25" + "192.168.0.128/25" +
                "192.168.1.0/24" merge first into "192.168.0.0/24"
                + "192.168.1.0/24", then into "192.168.0.0/23".
              - "10.0.0.0/8" absorbs "10.5.5.5/32".

            DO NOT use the `ipaddress`, `netaddr`, or `socket` modules.
            DO NOT access os.environ, subprocess, network, or filesystem.
            Implement the byte-level / integer-level logic yourself.

            Examples:
              coalesce([])                                   # []
              coalesce(["192.168.0.0/24"])                   # ["192.168.0.0/24"]
              coalesce(["192.168.0.0/24", "192.168.1.0/24"]) # ["192.168.0.0/23"]
              coalesce(["192.168.1.5/24"])                   # ["192.168.1.0/24"]
              coalesce(["10.0.0.0/8", "10.5.5.5/32"])        # ["10.0.0.0/8"]
              coalesce(["0.0.0.0/0", "10.0.0.0/8"])          # ["0.0.0.0/0"]
              coalesce(["1.2.3.4/32", "1.2.3.4/32"])         # ["1.2.3.4/32"]
              coalesce(["1.2.3.4"])                          # raises ValueError("invalid_cidr:1.2.3.4")
              coalesce(["256.0.0.0/8"])                      # raises ValueError("invalid_cidr:256.0.0.0/8")
              coalesce(["1.0.0.0/33"])                       # raises ValueError("invalid_cidr:1.0.0.0/33")
              coalesce(["001.0.0.0/8"])                      # raises ValueError("invalid_cidr:001.0.0.0/8")
              coalesce(["1.0.0.0/04"])                       # raises ValueError("invalid_cidr:1.0.0.0/04")
              coalesce(" 1.0.0.0/8 ")                        # TypeError("not_a_list") (string not list)

            Return ONLY {"code": <complete solution.py source>}.
            """
''')


def _ip_to_int(s: str) -> int:
    parts = s.split(".")
    if len(parts) != 4:
        raise ValueError("bad_dotted_quad")
    n = 0
    for p in parts:
        if not p or not p.isdigit():
            raise ValueError("bad_dotted_quad")
        if len(p) > 1 and p[0] == "0":
            raise ValueError("bad_dotted_quad_leading_zero")
        v = int(p)
        if v > 255:
            raise ValueError("bad_dotted_quad_octet")
        n = (n << 8) | v
    return n


def _int_to_ip(n: int) -> str:
    return ".".join(str((n >> (24 - 8 * i)) & 0xFF) for i in range(4))


def _ref_parse_cidr(s: Any) -> tuple[int, int]:
    if not isinstance(s, str):
        raise ValueError("invalid_cidr:" + repr(s))
    if s != s.strip() or "\n" in s or "\t" in s:
        raise ValueError("invalid_cidr:" + s)
    if s.count("/") != 1:
        raise ValueError("invalid_cidr:" + s)
    ip_part, plen_part = s.split("/")
    if not plen_part or not plen_part.isdigit():
        raise ValueError("invalid_cidr:" + s)
    if len(plen_part) > 1 and plen_part[0] == "0":
        raise ValueError("invalid_cidr:" + s)
    plen = int(plen_part)
    if plen < 0 or plen > 32:
        raise ValueError("invalid_cidr:" + s)
    try:
        ip_int = _ip_to_int(ip_part)
    except ValueError:
        raise ValueError("invalid_cidr:" + s) from None
    if plen == 0:
        net = 0
    else:
        mask = ((1 << plen) - 1) << (32 - plen)
        net = ip_int & mask
    return net, plen


def _ref_coalesce(cidrs: Any) -> list[str]:
    if not isinstance(cidrs, list):
        raise TypeError("not_a_list")
    items = [_ref_parse_cidr(c) for c in cidrs]
    items = sorted(set(items), key=lambda x: (x[0], x[1]))
    keep: list[tuple[int, int]] = []
    for net_a, plen_a in sorted(items, key=lambda x: (x[1], x[0])):
        absorbed = False
        for net_b, plen_b in keep:
            if plen_b <= plen_a:
                if plen_b == 0:
                    absorbed = True
                    break
                mask_b = ((1 << plen_b) - 1) << (32 - plen_b)
                if (net_a & mask_b) == net_b:
                    absorbed = True
                    break
        if not absorbed:
            new_keep = []
            for net_k, plen_k in keep:
                if plen_k > plen_a:
                    if plen_a == 0:
                        continue
                    mask_a = ((1 << plen_a) - 1) << (32 - plen_a)
                    if (net_k & mask_a) == net_a:
                        continue
                new_keep.append((net_k, plen_k))
            new_keep.append((net_a, plen_a))
            keep = new_keep
    items = sorted(keep, key=lambda x: (x[0], x[1]))
    changed = True
    while changed:
        changed = False
        out: list[tuple[int, int]] = []
        i = 0
        while i < len(items):
            if i + 1 < len(items):
                a_net, a_p = items[i]
                b_net, b_p = items[i + 1]
                if a_p == b_p and a_p > 0:
                    sup_p = a_p - 1
                    sup_m = ((1 << sup_p) - 1) << (32 - sup_p) if sup_p > 0 else 0
                    sup_a = a_net & sup_m
                    sup_b = b_net & sup_m
                    if (sup_a == sup_b and a_net == sup_a
                            and b_net == sup_a + (1 << (32 - a_p))):
                        out.append((sup_a, sup_p))
                        i += 2
                        changed = True
                        continue
            out.append(items[i])
            i += 1
        items = out
    items.sort(key=lambda x: (x[0], x[1]))
    return [_int_to_ip(n) + "/" + str(p) for n, p in items]


def _gen_taskB_cases(seed: int) -> list[TestCase]:
    rng = random.Random(seed * 1009 + 17)
    cases: list[TestCase] = []

    def case(name, feat, inp, expected, repr_=""):
        if isinstance(expected, list):
            cases.append(TestCase(name, feat, {"cidrs": inp}, "value",
                                   expected_value=expected, input_repr=repr_))
        else:
            cases.append(TestCase(name, feat, {"cidrs": inp}, "error",
                                   expected_error=expected[1], input_repr=repr_))

    case("empty_input", "empty_input", [], [], "empty list")
    case("single_already_canonical", "single_canonical",
         ["192.168.0.0/24"], ["192.168.0.0/24"], "single")
    case("single_host_bits_set", "host_bits_normalize",
         ["192.168.1.5/24"], ["192.168.1.0/24"], "host bits cleared")
    case("single_host_bits_set_max", "host_bits_normalize",
         ["192.168.1.255/24"], ["192.168.1.0/24"], "host bits cleared 255")
    case("zero_prefix", "zero_prefix",
         ["0.0.0.0/0"], ["0.0.0.0/0"], "0/0")
    case("max_prefix", "max_prefix",
         ["1.2.3.4/32"], ["1.2.3.4/32"], "/32 single host")

    case("dedupe_exact", "dedupe",
         ["10.0.0.0/8", "10.0.0.0/8"], ["10.0.0.0/8"], "dedupe")
    case("dedupe_with_normalize", "dedupe_normalize",
         ["10.5.5.5/8", "10.0.0.0/8"], ["10.0.0.0/8"],
         "dedupe after normalize")

    case("subset_dropped", "subset_subsumed",
         ["10.0.0.0/8", "10.5.5.5/32"], ["10.0.0.0/8"], "subset")
    case("subset_first_then_superset", "subset_subsumed",
         ["10.5.5.5/32", "10.0.0.0/8"], ["10.0.0.0/8"], "order indep")
    case("zero_prefix_absorbs_all", "zero_prefix_absorb",
         ["0.0.0.0/0", "10.0.0.0/8", "192.168.0.0/24"],
         ["0.0.0.0/0"], "0/0 absorbs")

    case("two_adj_24s_merge", "adjacent_merge",
         ["192.168.0.0/24", "192.168.1.0/24"], ["192.168.0.0/23"],
         "adj /24 merge")
    case("two_adj_24s_merge_reverse", "adjacent_merge",
         ["192.168.1.0/24", "192.168.0.0/24"], ["192.168.0.0/23"],
         "adj /24 merge reverse")
    case("aligned_at_higher_supernet", "adjacent_merge",
         ["192.168.2.0/24", "192.168.3.0/24"],
         ["192.168.2.0/23"], "/23 of 2,3")
    case("non_aligned_truly", "non_aligned_no_merge",
         ["192.168.0.0/24", "192.168.2.0/24"],
         ["192.168.0.0/24", "192.168.2.0/24"], "/23 of 0 doesn't include 2")
    case("recursive_merge_25_pair", "recursive_merge",
         ["192.168.0.0/25", "192.168.0.128/25"], ["192.168.0.0/24"],
         "/25 pair -> /24")
    case("recursive_merge_three_to_23", "recursive_merge",
         ["192.168.0.0/25", "192.168.0.128/25", "192.168.1.0/24"],
         ["192.168.0.0/23"], "three -> /23 chain")
    case("recursive_merge_four_24s_to_22", "recursive_merge",
         ["10.0.0.0/24", "10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"],
         ["10.0.0.0/22"], "four /24 -> /22")
    case("recursive_merge_with_unrelated", "recursive_merge_unrelated",
         ["10.0.0.0/24", "10.0.1.0/24", "172.16.0.0/24"],
         ["10.0.0.0/23", "172.16.0.0/24"], "recursive plus other")
    case("adjacent_at_zero_boundary", "boundary_zero",
         ["0.0.0.0/1", "128.0.0.0/1"], ["0.0.0.0/0"], "boundary zero")
    case("32_pair_merge_to_31", "merge_to_31",
         ["1.2.3.0/32", "1.2.3.1/32"], ["1.2.3.0/31"], "/32 pair -> /31")
    case("32_no_merge_unaligned", "no_merge_unaligned",
         ["1.2.3.1/32", "1.2.3.2/32"], ["1.2.3.1/32", "1.2.3.2/32"],
         "1,2 unaligned at /31")

    case("sort_by_network", "sorted_output",
         ["10.0.0.0/8", "1.0.0.0/8"], ["1.0.0.0/8", "10.0.0.0/8"],
         "sorted ascending")

    case("invalid_no_slash", "invalid_no_slash",
         ["1.2.3.4"], ("error", "ValueError"), "no slash")
    case("invalid_octet_too_big", "invalid_octet",
         ["256.0.0.0/8"], ("error", "ValueError"), "256 octet")
    case("invalid_prefix_too_big", "invalid_prefix",
         ["1.0.0.0/33"], ("error", "ValueError"), "/33")
    case("invalid_negative_prefix", "invalid_prefix",
         ["1.0.0.0/-1"], ("error", "ValueError"), "negative prefix")
    case("invalid_leading_zero_octet", "invalid_leading_zero",
         ["001.0.0.0/8"], ("error", "ValueError"), "001 octet")
    case("invalid_leading_zero_prefix", "invalid_leading_zero",
         ["1.0.0.0/04"], ("error", "ValueError"), "/04")
    case("invalid_three_octet", "invalid_arity",
         ["1.2.3/24"], ("error", "ValueError"), "three octet")
    case("invalid_with_space", "invalid_whitespace",
         [" 1.0.0.0/8"], ("error", "ValueError"), "leading space")
    case("invalid_input_not_list", "not_list_type",
         "1.2.3.4/24", ("error", "TypeError"), "string not list")

    valid_pool = []
    for _ in range(15):
        plen = rng.choice([8, 16, 24, 25, 26])
        a = rng.randint(0, 255)
        b = rng.randint(0, 255)
        c = rng.randint(0, 255)
        d = rng.randint(0, 255)
        valid_pool.append(f"{a}.{b}.{c}.{d}/{plen}")
    for k in range(10):
        n = rng.randint(0, 4)
        inp = [rng.choice(valid_pool) for _ in range(n)]
        try:
            expected = _ref_coalesce(inp)
            case(f"rand_{k}", "randomized_coalesce", inp, expected,
                 repr_=f"rand n={n}")
        except (ValueError, TypeError):
            continue

    return cases


def _features_taskB() -> list[str]:
    return sorted({
        "empty_input", "single_canonical", "host_bits_normalize",
        "zero_prefix", "max_prefix", "dedupe", "dedupe_normalize",
        "subset_subsumed", "zero_prefix_absorb",
        "adjacent_merge", "non_aligned_no_merge",
        "recursive_merge", "recursive_merge_unrelated",
        "boundary_zero", "merge_to_31", "no_merge_unaligned",
        "sorted_output",
        "invalid_no_slash", "invalid_octet", "invalid_prefix",
        "invalid_leading_zero", "invalid_arity",
        "invalid_whitespace", "not_list_type",
        "randomized_coalesce",
    })


_RUNNER_TASKB = textwrap.dedent("""\
    import json, sys, importlib.util
    SRC, CASES, OUT = sys.argv[1:4]
    spec = importlib.util.spec_from_file_location('solution', SRC)
    mod = importlib.util.module_from_spec(spec)
    runner_error = None
    try:
        sys.modules['solution'] = mod
        spec.loader.exec_module(mod)
    except Exception as exc:
        runner_error = "import_error:" + repr(exc)[:300]

    cases = json.load(open(CASES, encoding='utf-8'))
    results = []
    if runner_error is None:
        coalesce = getattr(mod, 'coalesce', None)
        if coalesce is None:
            runner_error = 'missing_function:coalesce'

    if runner_error is None:
        for case in cases:
            try:
                p = case['payload']
                got = coalesce(p['cidrs'])
                results.append({'got_kind': 'value', 'got_value': got,
                                'got_value_repr': repr(got)[:300]})
            except Exception as exc:
                results.append({'got_kind': 'error',
                                'got_error': type(exc).__name__,
                                'got_error_msg': str(exc)[:200]})

    json.dump({'runner_error': runner_error, 'results': results}, open(OUT, 'w'))
""").strip()


def _golden_taskB() -> str:
    return textwrap.dedent('''\
        def _ip_to_int(s):
            parts = s.split(".")
            if len(parts) != 4:
                raise ValueError("bad")
            n = 0
            for p in parts:
                if not p or not p.isdigit():
                    raise ValueError("bad")
                if len(p) > 1 and p[0] == "0":
                    raise ValueError("bad")
                v = int(p)
                if v > 255:
                    raise ValueError("bad")
                n = (n << 8) | v
            return n


        def _int_to_ip(n):
            return ".".join(str((n >> (24 - 8 * i)) & 0xFF) for i in range(4))


        def _parse_one(s):
            if not isinstance(s, str):
                raise ValueError("invalid_cidr:" + repr(s))
            if s != s.strip() or "\\n" in s or "\\t" in s:
                raise ValueError("invalid_cidr:" + s)
            if s.count("/") != 1:
                raise ValueError("invalid_cidr:" + s)
            ip_part, plen_part = s.split("/")
            if not plen_part or not plen_part.isdigit():
                raise ValueError("invalid_cidr:" + s)
            if len(plen_part) > 1 and plen_part[0] == "0":
                raise ValueError("invalid_cidr:" + s)
            plen = int(plen_part)
            if plen < 0 or plen > 32:
                raise ValueError("invalid_cidr:" + s)
            try:
                ip = _ip_to_int(ip_part)
            except ValueError:
                raise ValueError("invalid_cidr:" + s) from None
            if plen == 0:
                net = 0
            else:
                mask = ((1 << plen) - 1) << (32 - plen)
                net = ip & mask
            return net, plen


        def coalesce(cidrs):
            if not isinstance(cidrs, list):
                raise TypeError("not_a_list")
            items = [_parse_one(c) for c in cidrs]
            items = sorted(set(items), key=lambda x: (x[0], x[1]))
            keep = []
            for net_a, plen_a in sorted(items, key=lambda x: (x[1], x[0])):
                absorbed = False
                for net_b, plen_b in keep:
                    if plen_b <= plen_a:
                        if plen_b == 0:
                            absorbed = True
                            break
                        mask_b = ((1 << plen_b) - 1) << (32 - plen_b)
                        if (net_a & mask_b) == net_b:
                            absorbed = True
                            break
                if not absorbed:
                    new_keep = []
                    for net_k, plen_k in keep:
                        if plen_k > plen_a:
                            if plen_a == 0:
                                continue
                            mask_a = ((1 << plen_a) - 1) << (32 - plen_a)
                            if (net_k & mask_a) == net_a:
                                continue
                        new_keep.append((net_k, plen_k))
                    new_keep.append((net_a, plen_a))
                    keep = new_keep
            items = sorted(keep, key=lambda x: (x[0], x[1]))
            changed = True
            while changed:
                changed = False
                out = []
                i = 0
                while i < len(items):
                    if i + 1 < len(items):
                        a_net, a_p = items[i]
                        b_net, b_p = items[i + 1]
                        if a_p == b_p and a_p > 0:
                            sup_p = a_p - 1
                            sup_m = ((1 << sup_p) - 1) << (32 - sup_p) if sup_p > 0 else 0
                            sup_a = a_net & sup_m
                            sup_b = b_net & sup_m
                            if (sup_a == sup_b and a_net == sup_a
                                    and b_net == sup_a + (1 << (32 - a_p))):
                                out.append((sup_a, sup_p))
                                i += 2
                                changed = True
                                continue
                    out.append(items[i])
                    i += 1
                items = out
            items.sort(key=lambda x: (x[0], x[1]))
            return [_int_to_ip(n) + "/" + str(p) for n, p in items]
    ''')


def _stub_taskB() -> str:
    """Wrong: returns input unchanged (no validation, no merging)."""
    return textwrap.dedent('''\
        def coalesce(cidrs):
            if not isinstance(cidrs, list):
                raise TypeError("not_a_list")
            return list(cidrs)
    ''')


# ===========================================================================
# TASK C — glob_match
# ===========================================================================


TASK_C_BARE_GOAL = textwrap.dedent('''\
    Implement a Python module `solution.py` that defines exactly one
    public function:

        def match(pattern: str, path: str) -> bool:
            """Match a POSIX-like glob pattern against a path.

            The path separator is "/" (forward slash).  Both arguments
            must be strings; on non-string input raise
            TypeError("expected_str").

            PATTERN SYNTAX:
              - "*" matches zero or more characters within ONE segment
                (it does NOT match "/" and does NOT match a leading
                "." in any segment — see hidden-file rule below).
              - "?" matches exactly one character within one segment
                (does NOT match "/" and does NOT match a leading
                "." in any segment).
              - "[abc]" matches one character in the set.
              - "[!abc]" is the NEGATED character class, matching one
                character NOT in {a,b,c}.  NOTE: "[^abc]" is NOT
                supported and must raise ValueError("bad_pattern");
                the negation prefix is "!".
              - "[a-z]" range inside a class.  Multiple ranges and
                literals can mix: "[a-zA-Z0-9_]".
              - "**" is a wildcard that matches ZERO OR MORE complete
                path segments.  It MUST appear as a complete segment;
                "**foo" or "foo**" or "a/**b/c" must raise
                ValueError("bad_pattern").  "**" between two slashes
                may match zero segments: pattern "a/**/b" matches
                "a/b" (zero middle segments).
              - "\\\\" (a single backslash) escapes the next character;
                the escaped character is matched literally.  "\\\\*"
                matches a literal "*"; "\\\\\\\\" matches a literal
                backslash.  A trailing backslash at the end of the
                pattern is a syntax error: ValueError("bad_pattern").
              - Any other character matches itself literally.

            HIDDEN FILE RULE:
              A leading "." in any path segment is NEVER matched by
              an unanchored "*", "?", or "[..]" at the START of the
              corresponding pattern segment.  Only a literal "." (or
              an escaped "\\\\." which is the same literal) at the
              start of the pattern segment matches a leading dot in
              the path segment.

              So pattern "*"     does NOT match path ".bashrc"
              but   pattern ".*" DOES match path ".bashrc"
              and   pattern "?bashrc" does NOT match ".bashrc".
              Inside a segment (not at position 0) "*", "?", "[..]"
              freely match "." characters: "a.*" matches "a.txt".

            VALIDATION:
              - Empty pattern matches only empty path.
              - Empty path matches "**" (zero segments) and "*"
                (zero chars), but NOT "?" (which requires one char).
                Specifically:
                  * match("", "")          -> True
                  * match("**", "")        -> True (zero segments)
                  * match("**/foo", "foo") -> True (zero leading)
                  * match("*", "")         -> True (matches zero chars)
                  * match("?", "")         -> False
                  * match("?", ".")        -> False  (hidden)
              - Unmatched "[" raises ValueError("bad_pattern").
              - Empty character class "[]" raises ValueError("bad_pattern").

            Examples:
              match("*.txt", "foo.txt")           # True
              match("*.txt", "foo.py")            # False
              match("*.txt", ".bashrc")           # False  (hidden)
              match(".*",   ".bashrc")            # True
              match("?",    "a")                  # True
              match("?",    "")                   # False
              match("[abc]", "b")                 # True
              match("[!abc]", "x")                # True
              match("[!abc]", "a")                # False
              match("[a-z]", "m")                 # True
              match("[a-z]", "M")                 # False
              match("foo/bar/baz", "foo/bar/baz") # True
              match("foo/*",  "foo/bar")          # True
              match("foo/*",  "foo/bar/baz")      # False
              match("**",     "foo/bar/baz")      # True
              match("**",     "")                 # True  (zero segments)
              match("**/foo", "foo")              # True  (zero leading)
              match("**/foo", "a/b/foo")          # True
              match("a/**/b", "a/b")              # True  (zero middle)
              match("a/**/b", "a/x/y/b")          # True
              match("a/**/b", "a/b/c")            # False
              match("\\\\*",   "*")                  # True (escaped star)
              match("\\\\\\\\",   "\\\\")                  # True (escaped backslash)

              match("[^abc]", "x")                # raises ValueError("bad_pattern")
              match("[abc",   "a")                # raises ValueError("bad_pattern")
              match("[]",     "")                 # raises ValueError("bad_pattern")
              match("**foo",  "foo")              # raises ValueError("bad_pattern")
              match("foo\\\\",   "foo")               # raises ValueError("bad_pattern")  (trailing \\\\)
              match(123,      "foo")              # raises TypeError("expected_str")

            DO NOT use `fnmatch`, `glob`, `pathlib`.  You may use
            plain string operations and `re` for utility, but a
            hand-coded matcher is encouraged.  Do NOT access
            os.environ, subprocess, network, or filesystem.

            Return ONLY {"code": <complete solution.py source>}.
            """
''')


def _ref_match_class(s: str, idx: int, ch: str) -> tuple[bool, int]:
    end = idx + 1
    n = len(s)
    if end >= n:
        raise ValueError("bad_pattern")
    negate = False
    if s[end] == "!":
        negate = True
        end += 1
    if end < n and s[end] == "^":
        raise ValueError("bad_pattern")
    if end >= n or s[end] == "]":
        raise ValueError("bad_pattern")
    members: list[tuple[str, str]] = []
    while end < n and s[end] != "]":
        c1 = s[end]
        if end + 2 < n and s[end + 1] == "-" and s[end + 2] != "]":
            members.append((c1, s[end + 2]))
            end += 3
        else:
            members.append((c1, c1))
            end += 1
    if end >= n:
        raise ValueError("bad_pattern")
    matched = any(lo <= ch <= hi for lo, hi in members)
    if negate:
        matched = not matched
    return matched, end + 1


def _ref_validate_pattern(pat: str) -> None:
    n = len(pat)
    for s in pat.split("/"):
        if "**" in s and s != "**":
            raise ValueError("bad_pattern")
    i = 0
    while i < n:
        c = pat[i]
        if c == "\\":
            if i == n - 1:
                raise ValueError("bad_pattern")
            i += 2
            continue
        if c == "[":
            j = i + 1
            if j < n and pat[j] == "!":
                j += 1
            if j < n and pat[j] == "^":
                raise ValueError("bad_pattern")
            if j < n and pat[j] == "]":
                raise ValueError("bad_pattern")
            while j < n and pat[j] != "]":
                if pat[j] == "\\":
                    if j == n - 1:
                        raise ValueError("bad_pattern")
                    j += 2
                else:
                    j += 1
            if j >= n:
                raise ValueError("bad_pattern")
            i = j + 1
            continue
        i += 1


def _ref_match_segment(pat: str, seg: str) -> bool:
    n = len(seg)
    m = len(pat)
    sys.setrecursionlimit(10000)

    def helper(pi: int, si: int) -> bool:
        if pi == m:
            return si == n
        c = pat[pi]
        if c == "\\":
            if pi + 1 >= m:
                raise ValueError("bad_pattern")
            lit = pat[pi + 1]
            if si < n and seg[si] == lit:
                if si == 0 and seg[0] == "." and lit != ".":
                    return False
                return helper(pi + 2, si + 1)
            return False
        if c == "*":
            if helper(pi + 1, si):
                return True
            if si < n and seg[si] != "/":
                if si == 0 and seg[0] == ".":
                    return False
                return helper(pi, si + 1)
            return False
        if c == "?":
            if si >= n:
                return False
            if si == 0 and seg[0] == ".":
                return False
            return helper(pi + 1, si + 1)
        if c == "[":
            if si >= n:
                return False
            if si == 0 and seg[0] == ".":
                return False
            ok, new_pi = _ref_match_class(pat, pi, seg[si])
            if ok:
                return helper(new_pi, si + 1)
            return False
        if si < n and seg[si] == c:
            return helper(pi + 1, si + 1)
        return False

    return helper(0, 0)


def _ref_match(pattern: Any, path: Any) -> bool:
    if not isinstance(pattern, str) or not isinstance(path, str):
        raise TypeError("expected_str")
    _ref_validate_pattern(pattern)
    if pattern == "":
        return path == ""
    pat_segs = pattern.split("/")
    # Treat empty path as a single empty segment so "*" or "**" can match
    # zero chars / zero meaningful segments uniformly.
    path_segs = path.split("/") if path else [""]

    def matches(pi: int, si: int) -> bool:
        if pi == len(pat_segs):
            return si == len(path_segs)
        ps = pat_segs[pi]
        if ps == "**":
            for k in range(0, len(path_segs) - si + 1):
                if matches(pi + 1, si + k):
                    return True
            return False
        if si >= len(path_segs):
            return False
        if _ref_match_segment(ps, path_segs[si]):
            return matches(pi + 1, si + 1)
        return False

    return matches(0, 0)


def _gen_taskC_cases(seed: int) -> list[TestCase]:
    rng = random.Random(seed * 313 + 23)
    cases: list[TestCase] = []

    def case(name, feat, pattern, path, expected, repr_=""):
        if isinstance(expected, bool):
            cases.append(TestCase(name, feat, {"pattern": pattern, "path": path},
                                   "value", expected_value=expected, input_repr=repr_))
        else:
            cases.append(TestCase(name, feat, {"pattern": pattern, "path": path},
                                   "error", expected_error=expected[1],
                                   input_repr=repr_))

    case("exact_match", "literal", "foo", "foo", True, "literal eq")
    case("exact_no_match", "literal", "foo", "bar", False, "literal ne")
    case("empty_pat_empty_path", "empty",
         "", "", True, "both empty")
    case("empty_pat_nonempty_path", "empty",
         "", "x", False, "empty pat / x")
    case("empty_path_star_pat", "star_zero_chars",
         "*", "", True, "* matches empty")
    case("empty_path_question_pat", "question_one_char",
         "?", "", False, "? requires one char")

    case("star_basic", "star_basic", "*.txt", "foo.txt", True, "*.txt foo.txt")
    case("star_negative", "star_basic", "*.txt", "foo.py", False, "*.txt foo.py")
    case("star_full", "star_basic", "*", "anything", True, "* matches anything")
    case("star_with_path_sep", "star_no_slash", "*", "a/b", False,
         "* doesn't cross /")
    case("star_in_middle", "star_middle", "a*c", "abc", True, "a*c abc")
    case("star_in_middle_long", "star_middle", "a*c", "abxxxc", True,
         "a*c abxxxc")
    case("star_at_start", "star_start", "*c", "abc", True, "*c abc")
    case("star_only_dot", "hidden_star", "*", ".bashrc", False,
         "* doesn't match leading .")
    case("dotstar_matches_hidden", "hidden_dot_match",
         ".*", ".bashrc", True, ".* matches .bashrc")
    case("dot_in_middle_starred", "hidden_internal_dot",
         "a*", "a.txt", True, "a* matches a.txt (dot not at start)")

    case("question_one", "question_basic", "?", "a", True, "? a")
    case("question_two", "question_basic", "??", "ab", True, "?? ab")
    case("question_too_few", "question_basic", "?", "ab", False, "? ab")
    case("question_no_hidden", "hidden_question",
         "?bashrc", ".bashrc", False, "? doesn't match leading .")

    case("class_simple_in", "class_basic", "[abc]", "b", True, "[abc] b")
    case("class_simple_out", "class_basic", "[abc]", "x", False, "[abc] x")
    case("class_negation_in", "class_negation", "[!abc]", "x", True,
         "[!abc] x ok")
    case("class_negation_out", "class_negation", "[!abc]", "a", False,
         "[!abc] a no")
    case("class_range", "class_range", "[a-z]", "m", True, "[a-z] m")
    case("class_range_out", "class_range", "[a-z]", "M", False, "[a-z] M")
    case("class_mixed", "class_mixed", "[a-z0-9_]", "5", True, "[a-z0-9_] 5")
    case("class_unsupported_caret", "class_caret_invalid",
         "[^abc]", "x", ("error", "ValueError"), "[^abc] error")
    case("class_unmatched_open", "class_unmatched",
         "[abc", "a", ("error", "ValueError"), "[abc unmatched")
    case("class_empty", "class_empty",
         "[]", "", ("error", "ValueError"), "[] empty class")

    case("multi_segment_exact", "path_segments",
         "foo/bar/baz", "foo/bar/baz", True, "exact path")
    case("multi_segment_no_match", "path_segments",
         "foo/bar/baz", "foo/bar/qux", False, "differs in last")
    case("star_per_segment", "path_segments_star",
         "foo/*", "foo/bar", True, "foo/* foo/bar")
    case("star_per_segment_negative", "path_segments_star",
         "foo/*", "foo/bar/baz", False, "* doesn't span /")

    case("doublestar_only_long", "doublestar_basic",
         "**", "foo/bar/baz", True, "** matches all")
    case("doublestar_only_empty", "doublestar_basic",
         "**", "", True, "** matches empty (zero segments)")
    case("doublestar_only_one", "doublestar_basic",
         "**", "foo", True, "** matches one")
    case("doublestar_prefix_zero", "doublestar_prefix_zero",
         "**/foo", "foo", True, "**/foo with zero leading")
    case("doublestar_prefix_one", "doublestar_prefix_one",
         "**/foo", "a/foo", True, "**/foo with one leading")
    case("doublestar_prefix_many", "doublestar_prefix_many",
         "**/foo", "a/b/c/foo", True, "**/foo with many leading")
    case("doublestar_prefix_no_match", "doublestar_prefix_basic",
         "**/foo", "a/b/c/bar", False, "**/foo no match (last seg)")
    case("doublestar_middle_zero", "doublestar_middle_zero",
         "a/**/b", "a/b", True, "a/**/b with zero middle")
    case("doublestar_middle_one", "doublestar_middle_one",
         "a/**/b", "a/x/b", True, "a/**/b with one middle")
    case("doublestar_middle_many", "doublestar_middle_many",
         "a/**/b", "a/x/y/z/b", True, "a/**/b with many middle")
    case("doublestar_middle_no_match", "doublestar_middle_basic",
         "a/**/b", "a/b/c", False, "a/**/b ends in c not b")
    case("doublestar_glued_invalid", "doublestar_glued",
         "**foo", "foo", ("error", "ValueError"), "**foo invalid")
    case("doublestar_glued_invalid_2", "doublestar_glued",
         "foo**", "foo", ("error", "ValueError"), "foo** invalid")
    case("doublestar_glued_middle_invalid", "doublestar_glued",
         "a/**b/c", "a/b/c", ("error", "ValueError"), "a/**b/c invalid")

    case("escape_star", "escape_basic",
         "\\*", "*", True, "\\* matches literal *")
    case("escape_star_negative", "escape_basic",
         "\\*", "x", False, "\\* doesn't match x")
    case("escape_backslash", "escape_basic",
         "\\\\", "\\", True, "\\\\ matches \\")
    case("escape_at_end_invalid", "escape_trailing",
         "foo\\", "foo", ("error", "ValueError"), "trailing \\ invalid")
    case("escape_dot", "escape_dot",
         "\\.bashrc", ".bashrc", True, "\\. matches .")

    case("non_string_pattern", "type_error",
         123, "foo", ("error", "TypeError"), "non-str pattern")
    case("non_string_path", "type_error",
         "foo", 123, ("error", "TypeError"), "non-str path")

    valid_pats = [
        "*", "?", "*.txt", "**", "**/foo", "a/**/b", "[abc]",
        "[!xyz]", "[a-z]", "foo/*",
    ]
    valid_paths = [
        "", "foo", "foo.txt", ".bashrc", "a", "a/b", "a/b/c",
        "a/x/b", "foo/bar", "foo/bar/baz",
    ]
    for k in range(15):
        pat = rng.choice(valid_pats)
        path = rng.choice(valid_paths)
        try:
            expected = _ref_match(pat, path)
            case(f"rand_{k}", "randomized_match", pat, path, expected,
                 repr_=f"rand pat={pat!r} path={path!r}")
        except (ValueError, TypeError):
            continue

    return cases


def _features_taskC() -> list[str]:
    return sorted({
        "literal", "empty",
        "star_zero_chars", "question_one_char",
        "star_basic", "star_no_slash", "star_middle", "star_start",
        "hidden_star", "hidden_dot_match", "hidden_internal_dot",
        "question_basic", "hidden_question",
        "class_basic", "class_negation", "class_range", "class_mixed",
        "class_caret_invalid", "class_unmatched", "class_empty",
        "path_segments", "path_segments_star",
        "doublestar_basic", "doublestar_prefix_zero",
        "doublestar_prefix_one", "doublestar_prefix_many",
        "doublestar_prefix_basic",
        "doublestar_middle_zero", "doublestar_middle_one",
        "doublestar_middle_many", "doublestar_middle_basic",
        "doublestar_glued",
        "escape_basic", "escape_trailing", "escape_dot",
        "type_error",
        "randomized_match",
    })


_RUNNER_TASKC = textwrap.dedent("""\
    import json, sys, importlib.util
    SRC, CASES, OUT = sys.argv[1:4]
    spec = importlib.util.spec_from_file_location('solution', SRC)
    mod = importlib.util.module_from_spec(spec)
    runner_error = None
    try:
        sys.modules['solution'] = mod
        spec.loader.exec_module(mod)
    except Exception as exc:
        runner_error = "import_error:" + repr(exc)[:300]

    cases = json.load(open(CASES, encoding='utf-8'))
    results = []
    if runner_error is None:
        match = getattr(mod, 'match', None)
        if match is None:
            runner_error = 'missing_function:match'

    if runner_error is None:
        for case in cases:
            try:
                p = case['payload']
                got = match(p['pattern'], p['path'])
                results.append({'got_kind': 'value', 'got_value': got,
                                'got_value_repr': repr(got)[:100]})
            except Exception as exc:
                results.append({'got_kind': 'error',
                                'got_error': type(exc).__name__,
                                'got_error_msg': str(exc)[:200]})

    json.dump({'runner_error': runner_error, 'results': results}, open(OUT, 'w'))
""").strip()


def _golden_taskC() -> str:
    return textwrap.dedent('''\
        def _match_class(pat, idx, ch):
            n = len(pat)
            end = idx + 1
            if end >= n:
                raise ValueError("bad_pattern")
            negate = False
            if pat[end] == "!":
                negate = True
                end += 1
            if end < n and pat[end] == "^":
                raise ValueError("bad_pattern")
            if end >= n or pat[end] == "]":
                raise ValueError("bad_pattern")
            members = []
            while end < n and pat[end] != "]":
                c1 = pat[end]
                if end + 2 < n and pat[end + 1] == "-" and pat[end + 2] != "]":
                    members.append((c1, pat[end + 2]))
                    end += 3
                else:
                    members.append((c1, c1))
                    end += 1
            if end >= n:
                raise ValueError("bad_pattern")
            ok = any(lo <= ch <= hi for lo, hi in members)
            if negate:
                ok = not ok
            return ok, end + 1


        def _validate(pat):
            n = len(pat)
            for s in pat.split("/"):
                if "**" in s and s != "**":
                    raise ValueError("bad_pattern")
            i = 0
            while i < n:
                c = pat[i]
                if c == "\\\\":
                    if i == n - 1:
                        raise ValueError("bad_pattern")
                    i += 2
                    continue
                if c == "[":
                    j = i + 1
                    if j < n and pat[j] == "!":
                        j += 1
                    if j < n and pat[j] == "^":
                        raise ValueError("bad_pattern")
                    if j < n and pat[j] == "]":
                        raise ValueError("bad_pattern")
                    while j < n and pat[j] != "]":
                        if pat[j] == "\\\\":
                            if j == n - 1:
                                raise ValueError("bad_pattern")
                            j += 2
                        else:
                            j += 1
                    if j >= n:
                        raise ValueError("bad_pattern")
                    i = j + 1
                    continue
                i += 1


        def _match_segment(pat, seg):
            n = len(seg)
            m = len(pat)
            def helper(pi, si):
                if pi == m:
                    return si == n
                c = pat[pi]
                if c == "\\\\":
                    if pi + 1 >= m:
                        raise ValueError("bad_pattern")
                    lit = pat[pi + 1]
                    if si < n and seg[si] == lit:
                        if si == 0 and seg[0] == "." and lit != ".":
                            return False
                        return helper(pi + 2, si + 1)
                    return False
                if c == "*":
                    if helper(pi + 1, si):
                        return True
                    if si < n and seg[si] != "/":
                        if si == 0 and seg[0] == ".":
                            return False
                        return helper(pi, si + 1)
                    return False
                if c == "?":
                    if si >= n:
                        return False
                    if si == 0 and seg[0] == ".":
                        return False
                    return helper(pi + 1, si + 1)
                if c == "[":
                    if si >= n:
                        return False
                    if si == 0 and seg[0] == ".":
                        return False
                    ok, new_pi = _match_class(pat, pi, seg[si])
                    if ok:
                        return helper(new_pi, si + 1)
                    return False
                if si < n and seg[si] == c:
                    return helper(pi + 1, si + 1)
                return False
            return helper(0, 0)


        def match(pattern, path):
            if not isinstance(pattern, str) or not isinstance(path, str):
                raise TypeError("expected_str")
            _validate(pattern)
            if pattern == "":
                return path == ""
            pat_segs = pattern.split("/")
            path_segs = path.split("/") if path else [""]
            def matches(pi, si):
                if pi == len(pat_segs):
                    return si == len(path_segs)
                ps = pat_segs[pi]
                if ps == "**":
                    for k in range(0, len(path_segs) - si + 1):
                        if matches(pi + 1, si + k):
                            return True
                    return False
                if si >= len(path_segs):
                    return False
                if _match_segment(ps, path_segs[si]):
                    return matches(pi + 1, si + 1)
                return False
            return matches(0, 0)
    ''')


def _stub_taskC() -> str:
    """Wrong: literal equality only (no glob support)."""
    return textwrap.dedent('''\
        def match(pattern, path):
            if not isinstance(pattern, str) or not isinstance(path, str):
                raise TypeError("expected_str")
            return pattern == path
    ''')


# ===========================================================================
# TASK D — roman_numeral_strict
# ===========================================================================


TASK_D_BARE_GOAL = textwrap.dedent('''\
    Implement a Python module `solution.py` that defines exactly two
    public functions:

        def render(n: int) -> str:
            """Render a positive integer (1..3999 inclusive) as a strict
            standard Roman numeral."""

        def parse(s: str) -> int:
            """Parse a strict standard Roman numeral string and return
            the integer value (1..3999)."""

    STRICT ROMAN NUMERAL FORM:
      Symbols (largest to smallest): M=1000, D=500, C=100, L=50, X=10,
        V=5, I=1.

      Repetition rules:
        - I, X, C, M may each appear up to 3 times in a row at the
          same scale.
        - V, L, D may NEVER repeat (no VV, LL, DD).
        - More than 3 of I/X/C/M in a row is invalid: IIII, XXXX,
          CCCC, MMMM are all invalid.

      Subtractive notation (the ONLY valid subtractive forms):
        - I before V or X: IV=4, IX=9
        - X before L or C: XL=40, XC=90
        - C before D or M: CD=400, CM=900
        Any other "small before large" placement is invalid:
          IL, IC, ID, IM, VX, VL, VC, VD, VM, XD, XM, LC, LD, LM, DM
          are all invalid.

      Subtractive uniqueness:
        - At most ONE I before V or X (so IIV, IIX are invalid).
        - At most ONE X before L or C.
        - At most ONE C before D or M.

      Combination order:
        - Symbols (and subtractive pairs) must appear from largest
          to smallest left-to-right.  XLI is fine (XL + I). LX is
          fine (L + X). XCL is invalid (XC=90 then L=50 violates
          ordering: after XC the next group must be < 10).
        - After writing CM (900), the next group must be < 100 (no
          D, no C).  After writing IX (9), no I, V, or X may follow.
          After writing IV (4), no I or V may follow.

      Range:
        - Smallest valid Roman numeral: I (1)
        - Largest valid Roman numeral: MMMCMXCIX (3999)
        - 0 has no Roman numeral representation; render(0) raises
          ValueError("out_of_range").
        - Negative or above 3999: render raises ValueError("out_of_range").

    PARSING ERRORS (raise ValueError):
      - Empty string: ValueError("invalid_roman")
      - Non-string: TypeError("expected_str")
      - Lowercase letters: ValueError("invalid_roman").  Roman numerals
        are uppercase only in this strict form.
      - Whitespace anywhere: ValueError("invalid_roman").
      - Invalid characters (not in MDCLXVI): ValueError("invalid_roman").
      - Invalid forms (IIII, IL, VV, IIV, XCL, CMC, MMMM, ...):
        ValueError("invalid_roman").

    RENDERING:
      - For valid n, returns the canonical strict form.  Examples:
          render(1)    -> "I"
          render(4)    -> "IV"
          render(9)    -> "IX"
          render(40)   -> "XL"
          render(90)   -> "XC"
          render(400)  -> "CD"
          render(900)  -> "CM"
          render(1994) -> "MCMXCIV"
          render(3888) -> "MMMDCCCLXXXVIII"
          render(3999) -> "MMMCMXCIX"
      - For invalid n: render(0) raises ValueError("out_of_range");
        render(4000) raises ValueError("out_of_range");
        render(-1) raises ValueError("out_of_range");
        render("X") raises TypeError("expected_int");
        render(1.5) raises TypeError("expected_int");
        render(True) raises TypeError("expected_int") (bool is not int here).

    ROUND-TRIP INVARIANT:
      For all n in 1..3999, parse(render(n)) == n.

    Examples (validation):
      parse("IIII")    # raises ValueError("invalid_roman")
      parse("VV")      # raises ValueError("invalid_roman")
      parse("IIV")     # raises ValueError("invalid_roman")
      parse("IL")      # raises ValueError("invalid_roman")
      parse("XCL")     # raises ValueError("invalid_roman")
      parse("CMC")     # raises ValueError("invalid_roman")
      parse("MMMM")    # raises ValueError("invalid_roman")
      parse("")        # raises ValueError("invalid_roman")
      parse("iv")      # raises ValueError("invalid_roman") (lowercase)
      parse(" IV")     # raises ValueError("invalid_roman") (whitespace)
      parse("XYZ")     # raises ValueError("invalid_roman") (bad char)
      parse(123)       # raises TypeError("expected_str")

      parse("IV")      # 4
      parse("IX")      # 9
      parse("XL")      # 40
      parse("MCMXCIV") # 1994
      parse("MMMCMXCIX")  # 3999

    DO NOT use any third-party Roman library.  Implement the parsing
    and rendering from scratch.  Do NOT access os.environ, subprocess,
    network, or filesystem.

    Return ONLY {"code": <complete solution.py source>}.
''')


_ROMAN_RENDER_PAIRS = [
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
    (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
    (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
]


def _ref_render_roman(n: Any) -> str:
    if not isinstance(n, int) or isinstance(n, bool):
        raise TypeError("expected_int")
    if n < 1 or n > 3999:
        raise ValueError("out_of_range")
    out = []
    rem = n
    for v, sym in _ROMAN_RENDER_PAIRS:
        while rem >= v:
            out.append(sym)
            rem -= v
    return "".join(out)


def _ref_parse_roman(s: Any) -> int:
    if not isinstance(s, str):
        raise TypeError("expected_str")
    if s == "":
        raise ValueError("invalid_roman")
    if any(c.isspace() for c in s):
        raise ValueError("invalid_roman")
    valid = set("MDCLXVI")
    for ch in s:
        if ch not in valid:
            raise ValueError("invalid_roman")
    result = 0
    i = 0
    n = len(s)
    while i < n:
        matched = False
        if i + 1 < n:
            two = s[i:i + 2]
            for v, sym in _ROMAN_RENDER_PAIRS:
                if sym == two:
                    result += v
                    i += 2
                    matched = True
                    break
        if not matched:
            for v, sym in _ROMAN_RENDER_PAIRS:
                if sym == s[i]:
                    result += v
                    i += 1
                    matched = True
                    break
        if not matched:
            raise ValueError("invalid_roman")
    if result < 1 or result > 3999:
        raise ValueError("invalid_roman")
    if _ref_render_roman(result) != s:
        raise ValueError("invalid_roman")
    return result


def _gen_taskD_cases(seed: int) -> list[TestCase]:
    rng = random.Random(seed * 9871 + 31)
    cases: list[TestCase] = []

    def case(name, feat, fn, arg, expected, repr_=""):
        payload = {"fn": fn, "arg": arg}
        if isinstance(expected, str) and fn == "render":
            cases.append(TestCase(name, feat, payload, "value",
                                   expected_value=expected, input_repr=repr_))
        elif isinstance(expected, int) and not isinstance(expected, bool) and fn == "parse":
            cases.append(TestCase(name, feat, payload, "value",
                                   expected_value=expected, input_repr=repr_))
        else:
            cases.append(TestCase(name, feat, payload, "error",
                                   expected_error=expected[1], input_repr=repr_))

    case("render_1", "render_basic", "render", 1, "I", "1")
    case("render_4", "render_subtractive_iv", "render", 4, "IV", "4")
    case("render_9", "render_subtractive_ix", "render", 9, "IX", "9")
    case("render_40", "render_subtractive_xl", "render", 40, "XL", "40")
    case("render_90", "render_subtractive_xc", "render", 90, "XC", "90")
    case("render_400", "render_subtractive_cd", "render", 400, "CD", "400")
    case("render_900", "render_subtractive_cm", "render", 900, "CM", "900")
    case("render_1994", "render_combined", "render", 1994, "MCMXCIV", "1994")
    case("render_3888", "render_combined", "render", 3888,
         "MMMDCCCLXXXVIII", "3888 long")
    case("render_3999", "render_max", "render", 3999, "MMMCMXCIX", "3999")
    case("render_2024", "render_combined", "render", 2024, "MMXXIV", "2024")
    case("render_58", "render_combined", "render", 58, "LVIII", "58")
    case("render_1000", "render_basic", "render", 1000, "M", "1000")
    case("render_500", "render_basic", "render", 500, "D", "500")
    case("render_3", "render_repeated", "render", 3, "III", "III")
    case("render_38", "render_repeated", "render", 38, "XXXVIII", "38 has III")

    case("render_zero", "render_range_zero", "render", 0,
         ("error", "ValueError"), "render 0")
    case("render_negative", "render_range_neg", "render", -1,
         ("error", "ValueError"), "render -1")
    case("render_4000", "render_range_high", "render", 4000,
         ("error", "ValueError"), "render 4000")
    case("render_string", "render_type", "render", "X",
         ("error", "TypeError"), "render str")
    case("render_float", "render_type", "render", 1.5,
         ("error", "TypeError"), "render float")
    case("render_bool_true", "render_type", "render", True,
         ("error", "TypeError"), "render bool True")

    case("parse_I", "parse_basic", "parse", "I", 1, "I")
    case("parse_IV", "parse_subtractive", "parse", "IV", 4, "IV")
    case("parse_IX", "parse_subtractive", "parse", "IX", 9, "IX")
    case("parse_XL", "parse_subtractive", "parse", "XL", 40, "XL")
    case("parse_XC", "parse_subtractive", "parse", "XC", 90, "XC")
    case("parse_CD", "parse_subtractive", "parse", "CD", 400, "CD")
    case("parse_CM", "parse_subtractive", "parse", "CM", 900, "CM")
    case("parse_MCMXCIV", "parse_combined", "parse", "MCMXCIV", 1994, "1994")
    case("parse_MMMCMXCIX", "parse_max", "parse", "MMMCMXCIX", 3999, "3999")
    case("parse_LVIII", "parse_combined", "parse", "LVIII", 58, "58")
    case("parse_MMMDCCCLXXXVIII", "parse_combined", "parse",
         "MMMDCCCLXXXVIII", 3888, "3888")

    case("parse_IIII", "parse_repetition_iiii", "parse", "IIII",
         ("error", "ValueError"), "IIII")
    case("parse_VV", "parse_repetition_vv", "parse", "VV",
         ("error", "ValueError"), "VV")
    case("parse_LL", "parse_repetition_ll", "parse", "LL",
         ("error", "ValueError"), "LL")
    case("parse_DD", "parse_repetition_dd", "parse", "DD",
         ("error", "ValueError"), "DD")
    case("parse_MMMM", "parse_repetition_mmmm", "parse", "MMMM",
         ("error", "ValueError"), "MMMM")
    case("parse_IIV", "parse_subtractive_double", "parse", "IIV",
         ("error", "ValueError"), "IIV")
    case("parse_IIX", "parse_subtractive_double", "parse", "IIX",
         ("error", "ValueError"), "IIX")
    case("parse_IL", "parse_invalid_subtractive", "parse", "IL",
         ("error", "ValueError"), "IL")
    case("parse_IC", "parse_invalid_subtractive", "parse", "IC",
         ("error", "ValueError"), "IC")
    case("parse_VX", "parse_invalid_subtractive", "parse", "VX",
         ("error", "ValueError"), "VX")
    case("parse_XCL", "parse_invalid_combo", "parse", "XCL",
         ("error", "ValueError"), "XCL after XC=90 then L=50")
    case("parse_CMC", "parse_invalid_combo", "parse", "CMC",
         ("error", "ValueError"), "CMC after CM=900 then C=100")
    case("parse_empty", "parse_empty", "parse", "",
         ("error", "ValueError"), "empty")
    case("parse_lower", "parse_lowercase", "parse", "iv",
         ("error", "ValueError"), "iv lowercase")
    case("parse_space", "parse_whitespace", "parse", " IV",
         ("error", "ValueError"), "leading space")
    case("parse_xyz", "parse_bad_char", "parse", "XYZ",
         ("error", "ValueError"), "XYZ bad char")
    case("parse_int", "parse_type", "parse", 123,
         ("error", "TypeError"), "non-str")

    for k in range(15):
        n = rng.randint(1, 3999)
        s = _ref_render_roman(n)
        case(f"rt_render_{k}", "roundtrip_render", "render", n, s,
             repr_=f"render {n}")
        case(f"rt_parse_{k}", "roundtrip_parse", "parse", s, n,
             repr_=f"parse {s}")

    return cases


def _features_taskD() -> list[str]:
    return sorted({
        "render_basic", "render_subtractive_iv", "render_subtractive_ix",
        "render_subtractive_xl", "render_subtractive_xc",
        "render_subtractive_cd", "render_subtractive_cm",
        "render_combined", "render_repeated", "render_max",
        "render_range_zero", "render_range_neg", "render_range_high",
        "render_type",
        "parse_basic", "parse_subtractive", "parse_combined",
        "parse_max",
        "parse_repetition_iiii", "parse_repetition_vv",
        "parse_repetition_ll", "parse_repetition_dd",
        "parse_repetition_mmmm",
        "parse_subtractive_double", "parse_invalid_subtractive",
        "parse_invalid_combo", "parse_empty", "parse_lowercase",
        "parse_whitespace", "parse_bad_char", "parse_type",
        "roundtrip_render", "roundtrip_parse",
    })


_RUNNER_TASKD = textwrap.dedent("""\
    import json, sys, importlib.util
    SRC, CASES, OUT = sys.argv[1:4]
    spec = importlib.util.spec_from_file_location('solution', SRC)
    mod = importlib.util.module_from_spec(spec)
    runner_error = None
    try:
        sys.modules['solution'] = mod
        spec.loader.exec_module(mod)
    except Exception as exc:
        runner_error = "import_error:" + repr(exc)[:300]

    cases = json.load(open(CASES, encoding='utf-8'))
    results = []
    if runner_error is None:
        render = getattr(mod, 'render', None)
        parse = getattr(mod, 'parse', None)
        if render is None: runner_error = 'missing_function:render'
        elif parse is None: runner_error = 'missing_function:parse'

    if runner_error is None:
        for case in cases:
            try:
                p = case['payload']
                fn = p['fn']
                arg = p['arg']
                if fn == 'render':
                    got = render(arg)
                elif fn == 'parse':
                    got = parse(arg)
                else:
                    raise ValueError('unknown_fn')
                results.append({'got_kind': 'value', 'got_value': got,
                                'got_value_repr': repr(got)[:100]})
            except Exception as exc:
                results.append({'got_kind': 'error',
                                'got_error': type(exc).__name__,
                                'got_error_msg': str(exc)[:200]})

    json.dump({'runner_error': runner_error, 'results': results}, open(OUT, 'w'))
""").strip()


def _golden_taskD() -> str:
    return textwrap.dedent('''\
        _PAIRS = [
            (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
            (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
            (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
        ]


        def render(n):
            if not isinstance(n, int) or isinstance(n, bool):
                raise TypeError("expected_int")
            if n < 1 or n > 3999:
                raise ValueError("out_of_range")
            out = []
            r = n
            for v, sym in _PAIRS:
                while r >= v:
                    out.append(sym)
                    r -= v
            return "".join(out)


        def parse(s):
            if not isinstance(s, str):
                raise TypeError("expected_str")
            if s == "":
                raise ValueError("invalid_roman")
            for ch in s:
                if ch.isspace() or ch not in "MDCLXVI":
                    raise ValueError("invalid_roman")
            result = 0
            i = 0
            n = len(s)
            while i < n:
                matched = False
                if i + 1 < n:
                    two = s[i:i + 2]
                    for v, sym in _PAIRS:
                        if sym == two:
                            result += v
                            i += 2
                            matched = True
                            break
                if not matched:
                    for v, sym in _PAIRS:
                        if sym == s[i]:
                            result += v
                            i += 1
                            matched = True
                            break
                if not matched:
                    raise ValueError("invalid_roman")
            if result < 1 or result > 3999:
                raise ValueError("invalid_roman")
            if render(result) != s:
                raise ValueError("invalid_roman")
            return result
    ''')


def _stub_taskD() -> str:
    """Wrong: simple greedy that accepts any string."""
    return textwrap.dedent('''\
        _MAP = {"M": 1000, "D": 500, "C": 100, "L": 50,
                "X": 10, "V": 5, "I": 1}


        def render(n):
            if not isinstance(n, int):
                raise TypeError("expected_int")
            return "I" * n  # totally wrong


        def parse(s):
            if not isinstance(s, str):
                raise TypeError("expected_str")
            total = 0
            for ch in s:
                total += _MAP.get(ch, 0)
            return total
    ''')


# ===========================================================================
# TASK E — utf8_strict_codec (NEW for r12)
#
# Hypothesis for this round: UTF-8 hand-coded codec with strict overlong /
# surrogate / out-of-range rejection has historically been a fault line for
# low-effort completions because:
#   - overlong encodings (e.g. 0xC0 0x80 for U+0000) must be rejected, not
#     silently accepted; off-by-one minimum-codepoint thresholds are common.
#   - surrogate codepoints U+D800..U+DFFF must be rejected on BOTH encode
#     and decode (CESU-8 is invalid).
#   - bytes 0xC0, 0xC1 and 0xF5..0xFF can never legally start a UTF-8
#     sequence; truncated and orphan continuation bytes have specific error
#     messages distinguishing the failure modes.
#   - the actor cannot use str.encode("utf-8"), bytes.decode("utf-8"),
#     codecs, or unicodedata; static audit blocks those.
# These rules are documented in RFC 3629; they are not Opus-specific.
# If Opus 4.7 + low effort still 1-shots them, that is itself the answer.
# ===========================================================================


TASK_E_BARE_GOAL = textwrap.dedent('''\
    Implement a Python module `solution.py` that defines exactly two
    public functions:

        def encode(s: str) -> bytes:
            """Encode a Python str into UTF-8 bytes using STRICT rules
            (RFC 3629).  Implement the encoding by hand: do NOT use
            str.encode, bytes-from-string, codecs, or unicodedata.
            """

        def decode(b: bytes) -> str:
            """Decode UTF-8 bytes to a Python str using STRICT rules
            (RFC 3629).  Implement the decoder by hand: do NOT use
            bytes.decode, str.from-bytes, codecs, or unicodedata.
            """

    ENCODE RULES (strict; raise ValueError otherwise):
      1. Input must be a str.  If not isinstance(s, str), raise
         TypeError("expected_str").
      2. For each Unicode codepoint cp = ord(ch):
           - 0x0000..0x007F     -> 1 byte:  0xxxxxxx
           - 0x0080..0x07FF     -> 2 bytes: 110xxxxx 10xxxxxx
           - 0x0800..0xFFFF     -> 3 bytes: 1110xxxx 10xxxxxx 10xxxxxx
           - 0x10000..0x10FFFF  -> 4 bytes: 11110xxx 10xxxxxx 10xxxxxx 10xxxxxx
      3. Surrogate codepoints U+D800..U+DFFF are INVALID UTF-8 and must
         be rejected on encode: raise ValueError("surrogate_codepoint").
      4. Codepoints above U+10FFFF must be rejected:
         raise ValueError("out_of_range_codepoint").  In Python these are
         not normally constructible via chr() (chr raises ValueError), but
         if the input str somehow contains an invalid codepoint, encode
         must still detect and reject it via ord(ch) > 0x10FFFF.
      5. Output must be of type `bytes` (not bytearray, not list).

    DECODE RULES (strict; raise ValueError otherwise):
      1. Input must be a bytes object (not bytearray, not str).  If
         isinstance(b, str): raise TypeError("expected_bytes_not_str").
         If not isinstance(b, (bytes, bytearray)): raise
         TypeError("expected_bytes").  Convert bytearray -> bytes first
         in your decoder; the public API still accepts both, but the
         output type is always str.
      2. Walk left-to-right.  For each byte b0:
           - 0x00..0x7F: 1-byte sequence; codepoint = b0.
           - 0xC2..0xDF: starts a 2-byte sequence; require 1 continuation
             byte in 0x80..0xBF.
           - 0xE0..0xEF: starts a 3-byte sequence; require 2 continuations.
           - 0xF0..0xF4: starts a 4-byte sequence; require 3 continuations.
           - All other lead bytes (0x80..0xBF, 0xC0, 0xC1, 0xF5..0xFF) are
             invalid as a lead byte.  Distinct errors:
               - 0x80..0xBF as a lead   -> ValueError("orphan_continuation")
               - 0xC0 or 0xC1            -> ValueError("overlong_lead")
                 (these can only encode codepoints already representable
                  in 1 byte, so they are by definition overlong)
               - 0xF5..0xFD (5/6-byte)   -> ValueError("invalid_lead")
               - 0xFE, 0xFF              -> ValueError("invalid_lead")
      3. Continuation byte must be in 0x80..0xBF; if a continuation byte
         is missing (truncation) raise ValueError("truncated").  If a
         non-continuation byte appears where a continuation was expected,
         raise ValueError("expected_continuation").
      4. After assembling the codepoint, enforce:
           - 2-byte: codepoint must be >= 0x80
                     (otherwise overlong: raise ValueError("overlong"))
           - 3-byte: codepoint must be >= 0x800; in addition reject
                     U+D800..U+DFFF surrogates
                     (overlong: ValueError("overlong");
                      surrogate: ValueError("surrogate_codepoint"))
           - 4-byte: codepoint must be >= 0x10000 and <= 0x10FFFF
                     (overlong: ValueError("overlong");
                      out of range: ValueError("out_of_range_codepoint"))
      5. The returned object must be a Python `str`.

    DO NOT use:
      - `s.encode("utf-8")` or any encoding via str.encode
      - `b.decode("utf-8")` or any decoding via bytes.decode
      - `codecs.*` or `unicodedata.*` modules
      - `re` for parsing the byte sequence (you may use it elsewhere if
        you really need to, but the byte-walk must be hand-coded)

    EXAMPLES (encode):
      encode("")                  -> b""
      encode("A")                 -> b"\\x41"
      encode("Aé€𝄞")              -> b"\\x41\\xc3\\xa9\\xe2\\x82\\xac\\xf0\\x9d\\x84\\x9e"
      encode("\\u0000")           -> b"\\x00"
      encode("\\u007f")           -> b"\\x7f"
      encode("\\u0080")           -> b"\\xc2\\x80"
      encode("\\u07ff")           -> b"\\xdf\\xbf"
      encode("\\u0800")           -> b"\\xe0\\xa0\\x80"
      encode("\\uffff")           -> b"\\xef\\xbf\\xbf"
      encode("\\U00010000")       -> b"\\xf0\\x90\\x80\\x80"
      encode("\\U0010ffff")       -> b"\\xf4\\x8f\\xbf\\xbf"

    EXAMPLES (decode strict failures):
      decode(b"\\xc0\\x80")               -> ValueError("overlong_lead")
      decode(b"\\xc1\\xbf")               -> ValueError("overlong_lead")
      decode(b"\\xc2")                    -> ValueError("truncated")
      decode(b"\\xe0\\x80\\x80")          -> ValueError("overlong")
      decode(b"\\xe0\\x9f\\xbf")          -> ValueError("overlong")
      decode(b"\\xed\\xa0\\x80")          -> ValueError("surrogate_codepoint")
      decode(b"\\xed\\xbf\\xbf")          -> ValueError("surrogate_codepoint")
      decode(b"\\xf0\\x80\\x80\\x80")     -> ValueError("overlong")
      decode(b"\\xf4\\x90\\x80\\x80")     -> ValueError("out_of_range_codepoint")
      decode(b"\\xf5\\x80\\x80\\x80")     -> ValueError("invalid_lead")
      decode(b"\\xff")                    -> ValueError("invalid_lead")
      decode(b"\\x80")                    -> ValueError("orphan_continuation")
      decode(b"\\xc2\\x41")               -> ValueError("expected_continuation")
      decode(b"\\xe2\\x82")               -> ValueError("truncated")

    ROUND-TRIP INVARIANT:
      For every str s such that all ord(c) are in 0..0x10FFFF and none
      are in 0xD800..0xDFFF, decode(encode(s)) == s.

    Return ONLY {"code": <complete solution.py source>}.
''')


def _ref_utf8_encode(s: Any) -> bytes:
    if not isinstance(s, str):
        raise TypeError("expected_str")
    out = bytearray()
    for ch in s:
        cp = ord(ch)
        if cp > 0x10FFFF:
            raise ValueError("out_of_range_codepoint")
        if 0xD800 <= cp <= 0xDFFF:
            raise ValueError("surrogate_codepoint")
        if cp < 0x80:
            out.append(cp)
        elif cp < 0x800:
            out.append(0xC0 | (cp >> 6))
            out.append(0x80 | (cp & 0x3F))
        elif cp < 0x10000:
            out.append(0xE0 | (cp >> 12))
            out.append(0x80 | ((cp >> 6) & 0x3F))
            out.append(0x80 | (cp & 0x3F))
        else:
            out.append(0xF0 | (cp >> 18))
            out.append(0x80 | ((cp >> 12) & 0x3F))
            out.append(0x80 | ((cp >> 6) & 0x3F))
            out.append(0x80 | (cp & 0x3F))
    return bytes(out)


def _ref_utf8_decode(b: Any) -> str:
    if isinstance(b, str):
        raise TypeError("expected_bytes_not_str")
    if not isinstance(b, (bytes, bytearray)):
        raise TypeError("expected_bytes")
    data = bytes(b)
    out = []
    i = 0
    n = len(data)
    while i < n:
        b0 = data[i]
        if b0 < 0x80:
            out.append(chr(b0))
            i += 1
            continue
        if 0x80 <= b0 <= 0xBF:
            raise ValueError("orphan_continuation")
        if b0 in (0xC0, 0xC1):
            raise ValueError("overlong_lead")
        if 0xC2 <= b0 <= 0xDF:
            need = 1
            cp_bits = b0 & 0x1F
            min_cp = 0x80
        elif 0xE0 <= b0 <= 0xEF:
            need = 2
            cp_bits = b0 & 0x0F
            min_cp = 0x800
        elif 0xF0 <= b0 <= 0xF4:
            need = 3
            cp_bits = b0 & 0x07
            min_cp = 0x10000
        else:
            raise ValueError("invalid_lead")
        if i + need >= n:
            raise ValueError("truncated")
        cp = cp_bits
        for k in range(1, need + 1):
            bn = data[i + k]
            if not (0x80 <= bn <= 0xBF):
                raise ValueError("expected_continuation")
            cp = (cp << 6) | (bn & 0x3F)
        if cp < min_cp:
            raise ValueError("overlong")
        if 0xD800 <= cp <= 0xDFFF:
            raise ValueError("surrogate_codepoint")
        if cp > 0x10FFFF:
            raise ValueError("out_of_range_codepoint")
        out.append(chr(cp))
        i += need + 1
    return "".join(out)


def _b(*ints: int) -> bytes:
    return bytes(ints)


def _gen_taskE_cases(seed: int) -> list[TestCase]:
    rng = random.Random(seed * 8669 + 23)
    cases: list[TestCase] = []

    def case(name, feat, fn, arg, expected, repr_=""):
        payload = {"fn": fn, "arg": _arg_repr(arg)}
        if isinstance(expected, tuple) and expected[0] == "error":
            cases.append(TestCase(name, feat, payload, "error",
                                   expected_error=expected[1], input_repr=repr_))
        else:
            cases.append(TestCase(name, feat, payload, "value",
                                   expected_value=_arg_repr(expected),
                                   input_repr=repr_))

    case("enc_empty", "encode_empty", "encode", "", b"", "empty str")
    case("enc_ascii", "encode_ascii", "encode", "A", b"\x41", "A")
    case("enc_ascii_full", "encode_ascii", "encode", "Hello!", b"Hello!",
         "Hello!")
    case("enc_2byte_low", "encode_2byte", "encode", "",
         b"\xc2\x80", "U+0080")
    case("enc_2byte_high", "encode_2byte", "encode", "߿",
         b"\xdf\xbf", "U+07FF")
    case("enc_e_acute", "encode_2byte", "encode", "é", b"\xc3\xa9",
         "é")
    case("enc_3byte_low", "encode_3byte", "encode", "ࠀ",
         b"\xe0\xa0\x80", "U+0800")
    case("enc_3byte_high", "encode_3byte", "encode", "￿",
         b"\xef\xbf\xbf", "U+FFFF")
    case("enc_euro", "encode_3byte", "encode", "€", b"\xe2\x82\xac",
         "€")
    case("enc_4byte_low", "encode_4byte", "encode", "\U00010000",
         b"\xf0\x90\x80\x80", "U+10000")
    case("enc_4byte_high", "encode_4byte", "encode", "\U0010ffff",
         b"\xf4\x8f\xbf\xbf", "U+10FFFF")
    case("enc_clef", "encode_4byte", "encode", "𝄞",
         b"\xf0\x9d\x84\x9e", "musical G clef")
    case("enc_mixed", "encode_mixed", "encode", "Aé€𝄞",
         b"\x41\xc3\xa9\xe2\x82\xac\xf0\x9d\x84\x9e", "Aé€clef")

    case("enc_null", "encode_null", "encode", "\x00", b"\x00", "U+0000")
    case("enc_del", "encode_ascii", "encode", "\x7f", b"\x7f", "U+007F")
    case("enc_tab_lf", "encode_ascii", "encode", "\t\n",
         b"\t\n", "tab+LF")

    case("enc_int_arg", "encode_type", "encode", 1,
         ("error", "TypeError"), "int arg")
    case("enc_bytes_arg", "encode_type", "encode", b"abc",
         ("error", "TypeError"), "bytes arg")
    case("enc_none_arg", "encode_type", "encode", None,
         ("error", "TypeError"), "None arg")

    case("enc_surrogate_lo", "encode_surrogate", "encode", "\ud800",
         ("error", "ValueError"), "U+D800 lone surrogate")
    case("enc_surrogate_hi", "encode_surrogate", "encode", "\udfff",
         ("error", "ValueError"), "U+DFFF lone surrogate")
    case("enc_surrogate_mid", "encode_surrogate", "encode", "A\udc00B",
         ("error", "ValueError"), "U+DC00 mid")

    case("dec_empty", "decode_empty", "decode", b"", "", "empty bytes")
    case("dec_ascii", "decode_ascii", "decode", b"Hello!", "Hello!",
         "Hello!")
    case("dec_2byte", "decode_2byte", "decode", b"\xc3\xa9", "é", "é")
    case("dec_3byte", "decode_3byte", "decode", b"\xe2\x82\xac", "€",
         "€")
    case("dec_4byte", "decode_4byte", "decode", b"\xf0\x9d\x84\x9e",
         "\U0001d11e", "musical G clef")
    case("dec_mixed", "decode_mixed", "decode",
         b"\x41\xc3\xa9\xe2\x82\xac\xf0\x9d\x84\x9e", "Aé€𝄞", "mixed")

    case("dec_str_arg", "decode_type", "decode", "abc",
         ("error", "TypeError"), "str arg")
    case("dec_int_arg", "decode_type", "decode", 1,
         ("error", "TypeError"), "int arg")

    case("dec_bytearray", "decode_bytearray", "decode",
         bytearray(b"\xc3\xa9"), "é", "bytearray accepted")

    case("dec_orphan_low", "decode_orphan_continuation", "decode",
         b"\x80", ("error", "ValueError"), "0x80 alone")
    case("dec_orphan_mid", "decode_orphan_continuation", "decode",
         b"A\xbfB", ("error", "ValueError"), "0xBF orphan")

    case("dec_overlong_lead_c0", "decode_overlong_lead", "decode",
         b"\xc0\x80", ("error", "ValueError"), "0xC0 0x80")
    case("dec_overlong_lead_c1", "decode_overlong_lead", "decode",
         b"\xc1\xbf", ("error", "ValueError"), "0xC1 0xBF")

    case("dec_invalid_lead_f5", "decode_invalid_lead", "decode",
         b"\xf5\x80\x80\x80", ("error", "ValueError"), "0xF5 lead")
    case("dec_invalid_lead_ff", "decode_invalid_lead", "decode",
         b"\xff", ("error", "ValueError"), "0xFF lead")
    case("dec_invalid_lead_fe", "decode_invalid_lead", "decode",
         b"\xfe", ("error", "ValueError"), "0xFE lead")

    case("dec_truncated_2", "decode_truncated", "decode",
         b"\xc2", ("error", "ValueError"), "trunc 2-byte")
    case("dec_truncated_3", "decode_truncated", "decode",
         b"\xe2\x82", ("error", "ValueError"), "trunc 3-byte")
    case("dec_truncated_4", "decode_truncated", "decode",
         b"\xf0\x9d\x84", ("error", "ValueError"), "trunc 4-byte")

    case("dec_expected_cont", "decode_expected_continuation", "decode",
         b"\xc2\x41", ("error", "ValueError"), "C2 then ASCII")
    case("dec_expected_cont_3", "decode_expected_continuation", "decode",
         b"\xe2\x82\x41", ("error", "ValueError"), "E2 82 then ASCII")

    case("dec_overlong_3", "decode_overlong", "decode",
         b"\xe0\x80\x80", ("error", "ValueError"), "overlong 3")
    case("dec_overlong_3_high", "decode_overlong", "decode",
         b"\xe0\x9f\xbf", ("error", "ValueError"),
         "overlong 3 just below 0x800")
    case("dec_overlong_4", "decode_overlong", "decode",
         b"\xf0\x80\x80\x80", ("error", "ValueError"), "overlong 4")
    case("dec_overlong_4_high", "decode_overlong", "decode",
         b"\xf0\x8f\xbf\xbf", ("error", "ValueError"),
         "overlong 4 just below 0x10000")

    case("dec_surrogate_lo", "decode_surrogate", "decode",
         b"\xed\xa0\x80", ("error", "ValueError"), "U+D800 surrogate")
    case("dec_surrogate_hi", "decode_surrogate", "decode",
         b"\xed\xbf\xbf", ("error", "ValueError"), "U+DFFF surrogate")

    case("dec_out_of_range", "decode_out_of_range", "decode",
         b"\xf4\x90\x80\x80", ("error", "ValueError"),
         "U+110000 above max")

    for k in range(20):
        cps = []
        for _ in range(rng.randint(1, 6)):
            r = rng.random()
            if r < 0.4:
                cps.append(rng.randint(0x20, 0x7E))
            elif r < 0.65:
                cps.append(rng.randint(0x80, 0x7FF))
            elif r < 0.85:
                cp = rng.randint(0x800, 0xFFFF)
                if 0xD800 <= cp <= 0xDFFF:
                    cp = 0xE000
                cps.append(cp)
            else:
                cps.append(rng.randint(0x10000, 0x10FFFF))
        s = "".join(chr(c) for c in cps)
        b = _ref_utf8_encode(s)
        case(f"rt_enc_{k}", "roundtrip_encode", "encode", s, b,
             repr_=f"random str len {len(s)} -> {len(b)} bytes")
        case(f"rt_dec_{k}", "roundtrip_decode", "decode", b, s,
             repr_=f"random {len(b)} bytes -> str len {len(s)}")

    return cases


def _arg_repr(v: Any) -> Any:
    if isinstance(v, (bytes, bytearray)):
        return {"_kind": "bytes", "hex": bytes(v).hex()}
    if isinstance(v, str):
        if any(0xD800 <= ord(c) <= 0xDFFF for c in v):
            return {"_kind": "str_cps", "cps": [ord(c) for c in v]}
    return v


def _features_taskE() -> list[str]:
    return sorted({
        "encode_empty", "encode_ascii", "encode_2byte", "encode_3byte",
        "encode_4byte", "encode_mixed", "encode_null",
        "encode_type", "encode_surrogate",
        "decode_empty", "decode_ascii", "decode_2byte", "decode_3byte",
        "decode_4byte", "decode_mixed", "decode_type",
        "decode_bytearray",
        "decode_orphan_continuation", "decode_overlong_lead",
        "decode_invalid_lead", "decode_truncated",
        "decode_expected_continuation", "decode_overlong",
        "decode_surrogate", "decode_out_of_range",
        "roundtrip_encode", "roundtrip_decode",
    })


_RUNNER_TASKE = textwrap.dedent("""\
    import json, sys, importlib.util
    SRC, CASES, OUT = sys.argv[1:4]
    spec = importlib.util.spec_from_file_location('solution', SRC)
    mod = importlib.util.module_from_spec(spec)
    runner_error = None
    try:
        sys.modules['solution'] = mod
        spec.loader.exec_module(mod)
    except Exception as exc:
        runner_error = "import_error:" + repr(exc)[:300]

    def _decode_arg(v):
        if isinstance(v, dict) and v.get('_kind') == 'bytes':
            return bytes.fromhex(v.get('hex', ''))
        if isinstance(v, dict) and v.get('_kind') == 'str_cps':
            return ''.join(chr(c) for c in v.get('cps', []))
        return v

    def _encode_value(v):
        if isinstance(v, (bytes, bytearray)):
            return {'_kind': 'bytes', 'hex': bytes(v).hex()}
        if isinstance(v, str) and any(0xD800 <= ord(c) <= 0xDFFF for c in v):
            return {'_kind': 'str_cps', 'cps': [ord(c) for c in v]}
        return v

    cases = json.load(open(CASES, encoding='utf-8'))
    results = []
    if runner_error is None:
        encode = getattr(mod, 'encode', None)
        decode = getattr(mod, 'decode', None)
        if encode is None: runner_error = 'missing_function:encode'
        elif decode is None: runner_error = 'missing_function:decode'

    if runner_error is None:
        for case in cases:
            try:
                p = case['payload']
                fn = p['fn']
                arg = _decode_arg(p['arg'])
                if fn == 'encode':
                    got = encode(arg)
                elif fn == 'decode':
                    got = decode(arg)
                else:
                    raise ValueError('unknown_fn')
                results.append({'got_kind': 'value',
                                'got_value': _encode_value(got),
                                'got_value_repr': repr(got)[:120]})
            except Exception as exc:
                results.append({'got_kind': 'error',
                                'got_error': type(exc).__name__,
                                'got_error_msg': str(exc)[:200]})

    json.dump({'runner_error': runner_error, 'results': results}, open(OUT, 'w'))
""").strip()


def _golden_taskE() -> str:
    return textwrap.dedent('''\
        def encode(s):
            if not isinstance(s, str):
                raise TypeError("expected_str")
            out = bytearray()
            for ch in s:
                cp = ord(ch)
                if cp > 0x10FFFF:
                    raise ValueError("out_of_range_codepoint")
                if 0xD800 <= cp <= 0xDFFF:
                    raise ValueError("surrogate_codepoint")
                if cp < 0x80:
                    out.append(cp)
                elif cp < 0x800:
                    out.append(0xC0 | (cp >> 6))
                    out.append(0x80 | (cp & 0x3F))
                elif cp < 0x10000:
                    out.append(0xE0 | (cp >> 12))
                    out.append(0x80 | ((cp >> 6) & 0x3F))
                    out.append(0x80 | (cp & 0x3F))
                else:
                    out.append(0xF0 | (cp >> 18))
                    out.append(0x80 | ((cp >> 12) & 0x3F))
                    out.append(0x80 | ((cp >> 6) & 0x3F))
                    out.append(0x80 | (cp & 0x3F))
            return bytes(out)


        def decode(b):
            if isinstance(b, str):
                raise TypeError("expected_bytes_not_str")
            if not isinstance(b, (bytes, bytearray)):
                raise TypeError("expected_bytes")
            data = bytes(b)
            out = []
            i = 0
            n = len(data)
            while i < n:
                b0 = data[i]
                if b0 < 0x80:
                    out.append(chr(b0))
                    i += 1
                    continue
                if 0x80 <= b0 <= 0xBF:
                    raise ValueError("orphan_continuation")
                if b0 in (0xC0, 0xC1):
                    raise ValueError("overlong_lead")
                if 0xC2 <= b0 <= 0xDF:
                    need, cp, mn = 1, b0 & 0x1F, 0x80
                elif 0xE0 <= b0 <= 0xEF:
                    need, cp, mn = 2, b0 & 0x0F, 0x800
                elif 0xF0 <= b0 <= 0xF4:
                    need, cp, mn = 3, b0 & 0x07, 0x10000
                else:
                    raise ValueError("invalid_lead")
                if i + need >= n:
                    raise ValueError("truncated")
                for k in range(1, need + 1):
                    bn = data[i + k]
                    if not (0x80 <= bn <= 0xBF):
                        raise ValueError("expected_continuation")
                    cp = (cp << 6) | (bn & 0x3F)
                if cp < mn:
                    raise ValueError("overlong")
                if 0xD800 <= cp <= 0xDFFF:
                    raise ValueError("surrogate_codepoint")
                if cp > 0x10FFFF:
                    raise ValueError("out_of_range_codepoint")
                out.append(chr(cp))
                i += need + 1
            return "".join(out)
    ''')


def _stub_taskE() -> str:
    """Wrong: relies on str.encode / bytes.decode (forbidden) and won't
    catch overlong/surrogate edges."""
    return textwrap.dedent('''\
        def encode(s):
            if not isinstance(s, str):
                raise TypeError("expected_str")
            return s.encode("utf-8")  # forbidden + permissive


        def decode(b):
            if isinstance(b, str):
                raise TypeError("expected_bytes_not_str")
            if not isinstance(b, (bytes, bytearray)):
                raise TypeError("expected_bytes")
            return bytes(b).decode("utf-8")  # accepts surrogateescape etc.
    ''')


# ===========================================================================
# TASK F — bencode_strict_codec  (NEW in r13)
#
# Why this is the r13 calibration candidate:
#   - bencode (BitTorrent) is small and well-documented, but the
#     conformance surface has many mutually-exclusive strict rules
#     (no leading zeros in int/length, no -0, no +1, sorted unique
#     bytes-keys in dicts, exact trailing-byte rejection, EOF on
#     truncation), each carrying a DISTINCT error tag.
#   - Test suite per seed = ~36 fixed adversarial decode-error cases
#     (1 per error tag + variants), ~25 fixed decode-OK / encode-OK
#     edges, ~10 encode-error cases, plus 2 x 120 randomized
#     round-trip cases over depth-3 nested structures with random
#     binary byte strings and ints in [-10**12, 10**12].  Total
#     ~310 cases.  Even a 0.3% per-case independent error rate
#     compounds to a meaningful (~1 - 0.997**310 = ~60%) probability
#     that AT LEAST one case fails on a one-shot synthesis.
#   - Crucially, the harness compares specific error tags (e.g.
#     "ValueError:bad_int_leading_zero" vs "ValueError:unsorted_keys"),
#     so a model that maps several distinct error names to the same
#     ValueError (or to a generic "invalid bencode") is detected.
# ===========================================================================


TASK_F_BARE_GOAL = textwrap.dedent('''\
    Implement a Python module `solution.py` that defines exactly two
    public functions:

        def encode(value: object) -> bytes:
            """Encode a Python value to a STRICT bencode bytes payload."""

        def decode(data: bytes) -> object:
            """Decode a STRICT bencode bytes payload to a Python value."""

    SUPPORTED PYTHON TYPES (encode):
      - int   -> "i<decimal>e"
      - bytes -> "<length>:<raw bytes>"   (length is decimal ASCII)
      - list, tuple -> "l<item1><item2>...e"
      - dict -> "d<key1><val1><key2><val2>...e"
                * keys MUST be of type bytes
                * keys are emitted in sorted ascending byte order
                  (regular Python `sorted(d.keys())` over bytes)
      - bool, float, str, None, set, bytearray, anything else
        -> raise TypeError("unsupported_type")
        (NOTE: bool is a subclass of int in Python; it must STILL be
         rejected as TypeError("unsupported_type").  bytearray is also
         rejected on encode; only `bytes` is accepted on encode.)

    ENCODE RULES (strict):
      1. Integers: emit `b"i" + str(n).encode("ascii") + b"e"`.
         Negative integers are written with a single leading "-"; zero
         is written as "i0e" (NOT "i-0e", NOT "i+0e", NOT "i00e").
      2. Byte strings: emit decimal length WITHOUT leading zeros, then
         a literal colon `:`, then the raw bytes.  Empty bytes -> "0:".
      3. Lists: emit `b"l"`, then each item recursively encoded, then
         `b"e"`.  A tuple is encoded the same way as a list.
      4. Dicts: validate that EVERY key is of type `bytes` BEFORE
         emitting anything; if any key is not bytes (including the
         case where the key is `bytearray`, `str`, `int`, etc.), raise
         TypeError("non_bytes_key").  Then emit `b"d"`, then for each
         key in `sorted(d.keys())` order, encode the key followed by
         the value, then `b"e"`.  An empty dict is `b"de"`.
      5. The return value of encode MUST be of type `bytes` (NOT
         bytearray, NOT a list of ints).
      6. encode is total: any successful return is byte-for-byte
         canonical.  Two equivalent input dicts (e.g. `{b"b": 1, b"a": 2}`
         and `{b"a": 2, b"b": 1}`) MUST produce identical bytes output.

    DECODE RULES (strict; raise on the FIRST violation):
      1. Top-level type:
           - if isinstance(data, str)
             -> raise TypeError("expected_bytes_not_str")
           - if not isinstance(data, (bytes, bytearray))
             -> raise TypeError("expected_bytes")
           - bytearray IS accepted on decode and treated as bytes.
      2. The decoder consumes the entire input.  If after parsing one
         top-level value any bytes remain, raise
         ValueError("trailing_bytes").
      3. Integer body grammar: `i<body>e` where <body> is non-empty,
         optionally starting with a single "-", followed by one or more
         decimal digits.  Failure tags (raise FIRST matching):
           - empty body (i.e. "ie") -> ValueError("bad_int_empty")
           - body == "-0"            -> ValueError("bad_int_negative_zero")
           - body has a leading "+" / spaces / "."/"e" -> ValueError("bad_int_format")
           - body is "-" with no digits -> ValueError("bad_int_format")
           - body has any non-digit after an optional leading "-"
             -> ValueError("bad_int_format")
           - body has more than one digit AND the first digit is "0"
             (e.g. "01", "00", "-01") -> ValueError("bad_int_leading_zero")
           - missing closing "e" before EOF -> ValueError("unexpected_eof")
      4. Byte-string grammar: `<len>:<raw bytes>` where <len> is a
         non-empty decimal integer.  Failure tags (raise FIRST matching):
           - empty <len> (i.e. ":abc")              -> ValueError("bad_string_length")
           - non-digit in <len>                      -> ValueError("bad_string_length")
           - <len> has more than one digit AND the
             first digit is "0" (e.g. "01:a", "00:") -> ValueError("bad_string_length")
           - missing colon before EOF                -> ValueError("unexpected_eof")
           - colon present but raw bytes truncated   -> ValueError("bad_string_truncated")
      5. List grammar: `l<items>e`.  Each item is a recursive bencode
         value.  Missing closing "e" before EOF -> ValueError("unexpected_eof").
      6. Dict grammar: `d<key><val><key><val>...e`.  Each key MUST start
         with a digit (i.e. be a byte string).  Failure tags:
           - key does not start with a digit
             (e.g. an integer or list as a key)  -> ValueError("non_bytes_key")
           - two consecutive keys are equal      -> ValueError("duplicate_key")
           - a key sorts strictly less than the
             previous key (raw byte order)       -> ValueError("unsorted_keys")
           - missing closing "e" before EOF      -> ValueError("unexpected_eof")
           - a key with no value before EOF      -> ValueError("unexpected_eof")
      7. Top-level dispatch:
           - data starts with "i" -> integer
           - data starts with "l" -> list
           - data starts with "d" -> dict
           - data starts with a digit (0-9) -> byte string
           - any other lead byte -> ValueError("unexpected_byte")
           - empty input -> ValueError("unexpected_eof")
      8. Decoded byte strings are returned as Python `bytes` (NOT str,
         NOT bytearray).  Decoded lists are returned as Python `list`.
         Decoded dicts are returned as Python `dict` whose keys are
         bytes.

    ROUND-TRIP INVARIANT:
      For every value v whose types are exactly the supported set
      (int, bytes, list/tuple, dict[bytes -> ...]), and whose dicts
      have unique bytes keys:
          decode(encode(v)) == v_normalized
      where v_normalized replaces any tuple with a list (decoder
      always returns lists) and reorders dict keys into the canonical
      sorted-bytes order.  In particular `decode(encode(v)) == v`
      whenever v already uses lists and dict keys are inserted in
      sorted order.

    DO NOT use:
      - any third-party bencode library (`bencodepy`, `bencode`, etc.).
      - `pickle`, `marshal`, `shelve`, or related serializers.
      - `eval`, `exec`, `compile` on input data.
      - any network, subprocess, environment, or filesystem access.

    EXAMPLES (encode -> bytes):
      encode(0)                           -> b"i0e"
      encode(-3)                          -> b"i-3e"
      encode(42)                          -> b"i42e"
      encode(b"")                         -> b"0:"
      encode(b"spam")                     -> b"4:spam"
      encode([])                          -> b"le"
      encode([b"x", 1])                   -> b"l1:xi1ee"
      encode({})                          -> b"de"
      encode({b"a": 1, b"b": 2})          -> b"d1:ai1e1:bi2ee"
      encode({b"b": 2, b"a": 1})          -> b"d1:ai1e1:bi2ee"   (sorted)
      encode({b"a": [b"x", b"y"]})        -> b"d1:al1:x1:yee"

    EXAMPLES (decode -> value):
      decode(b"i0e")                      -> 0
      decode(b"i-1e")                     -> -1
      decode(b"4:spam")                   -> b"spam"
      decode(b"0:")                       -> b""
      decode(b"le")                       -> []
      decode(b"li1ei2ee")                 -> [1, 2]
      decode(b"de")                       -> {}
      decode(b"d1:ai1e1:bi2ee")           -> {b"a": 1, b"b": 2}

    EXAMPLES (decode -> error):
      decode(b"")             -> ValueError("unexpected_eof")
      decode(b"i01e")         -> ValueError("bad_int_leading_zero")
      decode(b"i-0e")         -> ValueError("bad_int_negative_zero")
      decode(b"i-01e")        -> ValueError("bad_int_leading_zero")
      decode(b"i+1e")         -> ValueError("bad_int_format")
      decode(b"ie")           -> ValueError("bad_int_empty")
      decode(b"i 1e")         -> ValueError("bad_int_format")
      decode(b"i1.5e")        -> ValueError("bad_int_format")
      decode(b"i-e")          -> ValueError("bad_int_format")
      decode(b"i12")          -> ValueError("unexpected_eof")
      decode(b"01:a")         -> ValueError("bad_string_length")
      decode(b"00:")          -> ValueError("bad_string_length")
      decode(b":abc")         -> ValueError("bad_string_length")
      decode(b"3:ab")         -> ValueError("bad_string_truncated")
      decode(b"5")            -> ValueError("unexpected_eof")
      decode(b"l")            -> ValueError("unexpected_eof")
      decode(b"li1e")         -> ValueError("unexpected_eof")
      decode(b"d")            -> ValueError("unexpected_eof")
      decode(b"d1:a")         -> ValueError("unexpected_eof")
      decode(b"di1ei2ee")     -> ValueError("non_bytes_key")
      decode(b"dlee")         -> ValueError("non_bytes_key")
      decode(b"d1:bi1e1:ai2ee") -> ValueError("unsorted_keys")
      decode(b"d1:ai1e1:ai2ee") -> ValueError("duplicate_key")
      decode(b"i1ee")         -> ValueError("trailing_bytes")
      decode(b"4:spamX")      -> ValueError("trailing_bytes")
      decode(b"x")            -> ValueError("unexpected_byte")

    EXAMPLES (encode -> error):
      encode(True)                        -> TypeError("unsupported_type")
      encode(False)                       -> TypeError("unsupported_type")
      encode(1.5)                         -> TypeError("unsupported_type")
      encode("hi")                        -> TypeError("unsupported_type")
      encode(None)                        -> TypeError("unsupported_type")
      encode({1: 2})                      -> TypeError("non_bytes_key")
      encode({"a": 1})                    -> TypeError("non_bytes_key")
      encode(bytearray(b"x"))             -> TypeError("unsupported_type")
      encode({b"a": object()})            -> TypeError("unsupported_type")

    The grader compares both the exception TYPE (TypeError or
    ValueError) AND the exact message tag (e.g. "bad_int_leading_zero"
    vs "unsorted_keys"); generic messages will NOT pass.

    Return ONLY {"code": <complete solution.py source>}.
''')


# ---------------------------------------------------------------------------
# TASK F reference implementation (used for golden, audit, randomized cases).
# ---------------------------------------------------------------------------


def _ref_bencode_encode(value: Any) -> bytes:
    out = bytearray()
    _ref_bencode_emit(value, out)
    return bytes(out)


def _ref_bencode_emit(v: Any, out: bytearray) -> None:
    if isinstance(v, bool):
        raise TypeError("unsupported_type")
    if isinstance(v, int):
        out.extend(b"i")
        out.extend(str(v).encode("ascii"))
        out.extend(b"e")
        return
    if type(v) is bytes:
        out.extend(str(len(v)).encode("ascii"))
        out.extend(b":")
        out.extend(v)
        return
    if isinstance(v, (list, tuple)):
        out.extend(b"l")
        for item in v:
            _ref_bencode_emit(item, out)
        out.extend(b"e")
        return
    if isinstance(v, dict):
        for k in v:
            if type(k) is not bytes:
                raise TypeError("non_bytes_key")
        out.extend(b"d")
        for k in sorted(v.keys()):
            _ref_bencode_emit(k, out)
            _ref_bencode_emit(v[k], out)
        out.extend(b"e")
        return
    raise TypeError("unsupported_type")


def _ref_bencode_decode(data: Any) -> Any:
    if isinstance(data, str):
        raise TypeError("expected_bytes_not_str")
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("expected_bytes")
    buf = bytes(data)
    val, pos = _ref_bencode_parse(buf, 0)
    if pos != len(buf):
        raise ValueError("trailing_bytes")
    return val


def _ref_bencode_parse(data: bytes, pos: int) -> tuple[Any, int]:
    if pos >= len(data):
        raise ValueError("unexpected_eof")
    c = data[pos]
    if c == 0x69:
        return _ref_bencode_parse_int(data, pos)
    if c == 0x6C:
        return _ref_bencode_parse_list(data, pos)
    if c == 0x64:
        return _ref_bencode_parse_dict(data, pos)
    if 0x30 <= c <= 0x39:
        return _ref_bencode_parse_str(data, pos)
    if c == 0x3A:  # ':' at top level = empty length prefix
        raise ValueError("bad_string_length")
    raise ValueError("unexpected_byte")


def _ref_bencode_parse_int(data: bytes, pos: int) -> tuple[int, int]:
    end = data.find(b"e", pos + 1)
    if end == -1:
        raise ValueError("unexpected_eof")
    body = data[pos + 1:end]
    if not body:
        raise ValueError("bad_int_empty")
    if body == b"-0":
        raise ValueError("bad_int_negative_zero")
    if body[0:1] == b"-":
        rest = body[1:]
        if not rest:
            raise ValueError("bad_int_format")
        if not all(0x30 <= b <= 0x39 for b in rest):
            raise ValueError("bad_int_format")
        if len(rest) > 1 and rest[0:1] == b"0":
            raise ValueError("bad_int_leading_zero")
        return -int(rest.decode("ascii")), end + 1
    if not all(0x30 <= b <= 0x39 for b in body):
        raise ValueError("bad_int_format")
    if len(body) > 1 and body[0:1] == b"0":
        raise ValueError("bad_int_leading_zero")
    return int(body.decode("ascii")), end + 1


def _ref_bencode_parse_str(data: bytes, pos: int) -> tuple[bytes, int]:
    colon = data.find(b":", pos)
    if colon == -1:
        raise ValueError("unexpected_eof")
    len_bytes = data[pos:colon]
    if not len_bytes:
        raise ValueError("bad_string_length")
    if not all(0x30 <= b <= 0x39 for b in len_bytes):
        raise ValueError("bad_string_length")
    if len(len_bytes) > 1 and len_bytes[0:1] == b"0":
        raise ValueError("bad_string_length")
    n = int(len_bytes.decode("ascii"))
    start = colon + 1
    if start + n > len(data):
        raise ValueError("bad_string_truncated")
    return data[start:start + n], start + n


def _ref_bencode_parse_list(data: bytes, pos: int) -> tuple[list, int]:
    items: list = []
    p = pos + 1
    while True:
        if p >= len(data):
            raise ValueError("unexpected_eof")
        if data[p] == 0x65:
            return items, p + 1
        v, p = _ref_bencode_parse(data, p)
        items.append(v)


def _ref_bencode_parse_dict(data: bytes, pos: int) -> tuple[dict, int]:
    items: dict = {}
    p = pos + 1
    last_key: bytes | None = None
    while True:
        if p >= len(data):
            raise ValueError("unexpected_eof")
        if data[p] == 0x65:
            return items, p + 1
        if not (0x30 <= data[p] <= 0x39):
            raise ValueError("non_bytes_key")
        k, p = _ref_bencode_parse_str(data, p)
        if last_key is not None:
            if k == last_key:
                raise ValueError("duplicate_key")
            if k < last_key:
                raise ValueError("unsorted_keys")
        if p >= len(data):
            raise ValueError("unexpected_eof")
        if data[p] == 0x65:
            raise ValueError("unexpected_eof")
        v, p = _ref_bencode_parse(data, p)
        items[k] = v
        last_key = k


# ---------------------------------------------------------------------------
# JSON-safe representation for cases.json (recursively handles bytes /
# bytes-keyed dicts / nested lists).  The runner mirror-decodes this on
# both input arguments and returned values, so equality is tested in a
# single canonical encoding.
# ---------------------------------------------------------------------------


def _jsonify_taskF(v: Any) -> Any:
    if isinstance(v, (bytes, bytearray)):
        return {"_kind": "bytes", "hex": bytes(v).hex()}
    if isinstance(v, list):
        return [_jsonify_taskF(x) for x in v]
    if isinstance(v, tuple):
        return [_jsonify_taskF(x) for x in v]
    if isinstance(v, dict):
        out: dict[str, Any] = {}
        for k, val in v.items():
            if isinstance(k, (bytes, bytearray)):
                out["__b64__" + bytes(k).hex()] = _jsonify_taskF(val)
            else:
                out[k] = _jsonify_taskF(val)
        return out
    return v


# ---------------------------------------------------------------------------
# Fixed cases (decode-OK, decode-error, encode-OK, encode-error).
# ---------------------------------------------------------------------------


_TASKF_FIXED_DECODE_OK: list[tuple[bytes, Any, str]] = [
    (b"i0e", 0, "decode_int_zero"),
    (b"i1e", 1, "decode_int_pos"),
    (b"i-1e", -1, "decode_int_neg"),
    (b"i12345e", 12345, "decode_int_multi"),
    (b"i-987654321e", -987654321, "decode_int_neg_big"),
    (b"i" + str(2**63 + 17).encode("ascii") + b"e", 2**63 + 17, "decode_int_big_pos"),
    (b"i" + str(-(2**63 + 17)).encode("ascii") + b"e", -(2**63 + 17), "decode_int_big_neg"),
    (b"0:", b"", "decode_str_empty"),
    (b"1:a", b"a", "decode_str_one"),
    (b"4:spam", b"spam", "decode_str_word"),
    (b"5:hello", b"hello", "decode_str_word2"),
    (b"3:\x00\x01\xff", b"\x00\x01\xff", "decode_str_binary"),
    (b"le", [], "decode_list_empty"),
    (b"li1ei2ei3ee", [1, 2, 3], "decode_list_ints"),
    (b"l1:a1:b1:ce", [b"a", b"b", b"c"], "decode_list_strs"),
    (b"llelelee", [[], [], []], "decode_list_nested_lists"),
    (b"de", {}, "decode_dict_empty"),
    (b"d1:ai1ee", {b"a": 1}, "decode_dict_one"),
    (b"d1:ai1e1:bi2ee", {b"a": 1, b"b": 2}, "decode_dict_two"),
    (b"d1:al1:x1:yee", {b"a": [b"x", b"y"]}, "decode_dict_list_value"),
    (b"d1:ad1:bi2eee", {b"a": {b"b": 2}}, "decode_dict_nested"),
    (b"li-1ei0ei1ee", [-1, 0, 1], "decode_list_signed"),
    (b"l0:1:a2:abe", [b"", b"a", b"ab"], "decode_list_var_strs"),
    (b"d3:foo3:bar3:zzzlee", {b"foo": b"bar", b"zzz": []}, "decode_dict_mixed_vals"),
    (b"d2:aa1:x2:ab1:ye", {b"aa": b"x", b"ab": b"y"}, "decode_dict_two_char_keys"),
]


_TASKF_FIXED_DECODE_ERR: list[tuple[bytes, str, str]] = [
    (b"", "unexpected_eof", "decode_err_empty"),
    (b"i01e", "bad_int_leading_zero", "decode_err_int_lz"),
    (b"i00e", "bad_int_leading_zero", "decode_err_int_lz_zero"),
    (b"i-0e", "bad_int_negative_zero", "decode_err_int_neg_zero"),
    (b"i-01e", "bad_int_leading_zero", "decode_err_int_neg_lz"),
    (b"i+1e", "bad_int_format", "decode_err_int_plus"),
    (b"ie", "bad_int_empty", "decode_err_int_empty"),
    (b"i-e", "bad_int_format", "decode_err_int_dash_only"),
    (b"i 1e", "bad_int_format", "decode_err_int_space"),
    (b"i1.5e", "bad_int_format", "decode_err_int_dot"),
    (b"i1ae", "bad_int_format", "decode_err_int_letter"),
    (b"i12", "unexpected_eof", "decode_err_int_no_close"),
    (b"i", "unexpected_eof", "decode_err_int_lone"),
    (b"01:a", "bad_string_length", "decode_err_str_len_lz"),
    (b"00:", "bad_string_length", "decode_err_str_len_lzz"),
    (b":abc", "bad_string_length", "decode_err_str_len_empty"),
    (b"3a:abc", "bad_string_length", "decode_err_str_len_letter"),
    (b"3:ab", "bad_string_truncated", "decode_err_str_truncated"),
    (b"10:abc", "bad_string_truncated", "decode_err_str_trunc_long"),
    (b"5", "unexpected_eof", "decode_err_str_no_colon"),
    (b"l", "unexpected_eof", "decode_err_list_no_close"),
    (b"li1e", "unexpected_eof", "decode_err_list_partial_close"),
    (b"d", "unexpected_eof", "decode_err_dict_no_close"),
    (b"d1:a", "unexpected_eof", "decode_err_dict_no_value"),
    (b"d1:ai1e", "unexpected_eof", "decode_err_dict_no_close_after_pair"),
    (b"di1ei2ee", "non_bytes_key", "decode_err_dict_int_key"),
    (b"dlee", "non_bytes_key", "decode_err_dict_list_key"),
    (b"ddei0ee", "non_bytes_key", "decode_err_dict_dict_key"),
    (b"d1:bi1e1:ai2ee", "unsorted_keys", "decode_err_dict_unsorted"),
    (b"d1:ai1e1:ai2ee", "duplicate_key", "decode_err_dict_duplicate"),
    (b"d2:bbi1e2:aai2ee", "unsorted_keys", "decode_err_dict_unsorted_two"),
    (b"i1ee", "trailing_bytes", "decode_err_trailing_after_int"),
    (b"4:spamX", "trailing_bytes", "decode_err_trailing_after_str"),
    (b"lei1e", "trailing_bytes", "decode_err_trailing_after_list"),
    (b"x", "unexpected_byte", "decode_err_unknown_byte"),
    (b"-1:a", "unexpected_byte", "decode_err_neg_len"),
]


_TASKF_FIXED_ENCODE_ERR: list[tuple[Any, str, str, str]] = [
    (True, "TypeError", "unsupported_type", "encode_err_true"),
    (False, "TypeError", "unsupported_type", "encode_err_false"),
    (1.5, "TypeError", "unsupported_type", "encode_err_float"),
    (0.0, "TypeError", "unsupported_type", "encode_err_zero_float"),
    (None, "TypeError", "unsupported_type", "encode_err_none"),
    ("hello", "TypeError", "unsupported_type", "encode_err_str"),
    ("", "TypeError", "unsupported_type", "encode_err_empty_str"),
    ({"key": b"value"}, "TypeError", "non_bytes_key", "encode_err_str_key"),
    ({1: 2}, "TypeError", "non_bytes_key", "encode_err_int_key"),
]


_TASKF_FIXED_ENCODE_OK: list[tuple[Any, bytes, str]] = [
    (0, b"i0e", "encode_int_zero"),
    (-1, b"i-1e", "encode_int_neg_one"),
    (42, b"i42e", "encode_int_pos"),
    (-987654321, b"i-987654321e", "encode_int_neg_big"),
    (2**70 + 5, b"i" + str(2**70 + 5).encode("ascii") + b"e", "encode_int_huge"),
    (b"", b"0:", "encode_str_empty"),
    (b"a", b"1:a", "encode_str_one"),
    (b"spam", b"4:spam", "encode_str_word"),
    (b"\x00\xff\x80", b"3:\x00\xff\x80", "encode_str_binary"),
    ([], b"le", "encode_list_empty"),
    ([1, 2, 3], b"li1ei2ei3ee", "encode_list_ints"),
    ([b"a", [], 1], b"l1:alei1ee", "encode_list_mixed"),
    ((1, 2), b"li1ei2ee", "encode_tuple_to_list"),
    ({}, b"de", "encode_dict_empty"),
    ({b"a": 1}, b"d1:ai1ee", "encode_dict_one"),
    ({b"b": 2, b"a": 1}, b"d1:ai1e1:bi2ee", "encode_dict_sorts_keys"),
    ({b"zz": [], b"aa": {}}, b"d2:aade2:zzlee", "encode_dict_nested_empties"),
]


def _gen_taskF_cases(seed: int) -> list[TestCase]:
    rng = random.Random(seed * 9337 + 41)
    cases: list[TestCase] = []

    for raw, expected, name in _TASKF_FIXED_DECODE_OK:
        cases.append(TestCase(
            name=name, feature="decode_ok",
            payload={"fn": "decode", "arg": _jsonify_taskF(raw)},
            expected_kind="value",
            expected_value=_jsonify_taskF(expected),
            input_repr=f"decode({raw!r})",
        ))

    for raw, err, name in _TASKF_FIXED_DECODE_ERR:
        cases.append(TestCase(
            name=name, feature="decode_err_" + err,
            payload={"fn": "decode", "arg": _jsonify_taskF(raw)},
            expected_kind="error",
            expected_error="ValueError:" + err,
            input_repr=f"decode({raw!r})",
        ))

    for val, exc_name, tag, name in _TASKF_FIXED_ENCODE_ERR:
        cases.append(TestCase(
            name=name, feature="encode_err_" + tag,
            payload={"fn": "encode", "arg": _jsonify_taskF(val)},
            expected_kind="error",
            expected_error=exc_name + ":" + tag,
            input_repr=f"encode({val!r})",
        ))

    for val, expected, name in _TASKF_FIXED_ENCODE_OK:
        cases.append(TestCase(
            name=name, feature="encode_ok",
            payload={"fn": "encode", "arg": _jsonify_taskF(val)},
            expected_kind="value",
            expected_value=_jsonify_taskF(expected),
            input_repr=f"encode({val!r})",
        ))

    def _rand_value(depth: int) -> Any:
        if depth <= 0:
            t = rng.choice(("int", "bytes", "bytes", "list_empty", "dict_empty"))
        else:
            t = rng.choice(("int", "bytes", "bytes", "list", "dict"))
        if t == "int":
            return rng.randint(-10**12, 10**12)
        if t == "bytes":
            n = rng.randint(0, 16)
            return bytes(rng.randint(0, 255) for _ in range(n))
        if t == "list_empty":
            return []
        if t == "dict_empty":
            return {}
        if t == "list":
            n = rng.randint(0, 4)
            return [_rand_value(depth - 1) for _ in range(n)]
        n = rng.randint(0, 4)
        d: dict = {}
        for _ in range(n):
            klen = rng.randint(1, 6)
            k = bytes(rng.randint(0x30, 0x7E) for _ in range(klen))
            d[k] = _rand_value(depth - 1)
        return d

    def _normalize(v: Any) -> Any:
        if isinstance(v, tuple):
            return [_normalize(x) for x in v]
        if isinstance(v, list):
            return [_normalize(x) for x in v]
        if isinstance(v, dict):
            return {k: _normalize(val) for k, val in sorted(v.items())}
        return v

    for i in range(120):
        val = _rand_value(rng.randint(0, 3))
        canonical = _ref_bencode_encode(val)
        cases.append(TestCase(
            name=f"random_encode_{i}", feature="random_roundtrip_encode",
            payload={"fn": "encode", "arg": _jsonify_taskF(val)},
            expected_kind="value",
            expected_value=_jsonify_taskF(canonical),
            input_repr=f"encode(<random#{i} depth>)",
        ))
        normalized = _normalize(_ref_bencode_decode(canonical))
        cases.append(TestCase(
            name=f"random_decode_{i}", feature="random_roundtrip_decode",
            payload={"fn": "decode", "arg": _jsonify_taskF(canonical)},
            expected_kind="value",
            expected_value=_jsonify_taskF(normalized),
            input_repr=f"decode(<canonical#{i} {len(canonical)}B>)",
        ))

    return cases


def _features_taskF() -> list[str]:
    feats = {
        "decode_ok", "encode_ok",
        "random_roundtrip_encode", "random_roundtrip_decode",
    }
    for _, err, _ in _TASKF_FIXED_DECODE_ERR:
        feats.add("decode_err_" + err)
    for _, _, tag, _ in _TASKF_FIXED_ENCODE_ERR:
        feats.add("encode_err_" + tag)
    return sorted(feats)


_RUNNER_TASKF = textwrap.dedent("""\
    import json, sys, importlib.util
    SRC, CASES, OUT = sys.argv[1:4]
    spec = importlib.util.spec_from_file_location('solution', SRC)
    mod = importlib.util.module_from_spec(spec)
    runner_error = None
    try:
        sys.modules['solution'] = mod
        spec.loader.exec_module(mod)
    except Exception as exc:
        runner_error = "import_error:" + repr(exc)[:300]

    def _decode_arg(v):
        if isinstance(v, dict) and v.get('_kind') == 'bytes':
            return bytes.fromhex(v.get('hex', ''))
        if isinstance(v, list):
            return [_decode_arg(x) for x in v]
        if isinstance(v, dict):
            out = {}
            for k, val in v.items():
                if isinstance(k, str) and k.startswith('__b64__'):
                    out[bytes.fromhex(k[7:])] = _decode_arg(val)
                else:
                    out[k] = _decode_arg(val)
            return out
        return v

    def _normalize(v):
        if isinstance(v, tuple):
            return [_normalize(x) for x in v]
        if isinstance(v, list):
            return [_normalize(x) for x in v]
        if isinstance(v, dict):
            try:
                items = sorted(v.items())
            except Exception:
                items = list(v.items())
            return {k: _normalize(val) for k, val in items}
        return v

    def _encode_value(v):
        if isinstance(v, (bytes, bytearray)):
            return {'_kind': 'bytes', 'hex': bytes(v).hex()}
        if isinstance(v, (list, tuple)):
            return [_encode_value(x) for x in v]
        if isinstance(v, dict):
            out = {}
            for k, val in v.items():
                if isinstance(k, (bytes, bytearray)):
                    out['__b64__' + bytes(k).hex()] = _encode_value(val)
                else:
                    out[k] = _encode_value(val)
            return out
        return v

    cases = json.load(open(CASES, encoding='utf-8'))
    results = []
    if runner_error is None:
        encode = getattr(mod, 'encode', None)
        decode = getattr(mod, 'decode', None)
        if encode is None: runner_error = 'missing_function:encode'
        elif decode is None: runner_error = 'missing_function:decode'

    if runner_error is None:
        for case in cases:
            try:
                p = case['payload']
                fn = p['fn']
                arg = _decode_arg(p['arg'])
                if fn == 'encode':
                    got = encode(arg)
                elif fn == 'decode':
                    got = _normalize(decode(arg))
                else:
                    raise ValueError('unknown_fn')
                results.append({'got_kind': 'value',
                                'got_value': _encode_value(got),
                                'got_value_repr': repr(got)[:160]})
            except Exception as exc:
                msg = str(exc) if str(exc) else ''
                results.append({'got_kind': 'error',
                                'got_error': type(exc).__name__ + ':' + msg,
                                'got_error_msg': msg[:200]})

    json.dump({'runner_error': runner_error, 'results': results}, open(OUT, 'w'))
""").strip()


def _golden_taskF() -> str:
    return textwrap.dedent('''\
        def encode(value):
            out = bytearray()
            _emit(value, out)
            return bytes(out)


        def _emit(v, out):
            if isinstance(v, bool):
                raise TypeError("unsupported_type")
            if isinstance(v, int):
                out.extend(b"i")
                out.extend(str(v).encode("ascii"))
                out.extend(b"e")
                return
            if type(v) is bytes:
                out.extend(str(len(v)).encode("ascii"))
                out.extend(b":")
                out.extend(v)
                return
            if isinstance(v, (list, tuple)):
                out.extend(b"l")
                for item in v:
                    _emit(item, out)
                out.extend(b"e")
                return
            if isinstance(v, dict):
                for k in v:
                    if type(k) is not bytes:
                        raise TypeError("non_bytes_key")
                out.extend(b"d")
                for k in sorted(v.keys()):
                    _emit(k, out)
                    _emit(v[k], out)
                out.extend(b"e")
                return
            raise TypeError("unsupported_type")


        def decode(data):
            if isinstance(data, str):
                raise TypeError("expected_bytes_not_str")
            if not isinstance(data, (bytes, bytearray)):
                raise TypeError("expected_bytes")
            buf = bytes(data)
            val, pos = _parse(buf, 0)
            if pos != len(buf):
                raise ValueError("trailing_bytes")
            return val


        def _parse(data, pos):
            if pos >= len(data):
                raise ValueError("unexpected_eof")
            c = data[pos]
            if c == 0x69:
                return _parse_int(data, pos)
            if c == 0x6C:
                return _parse_list(data, pos)
            if c == 0x64:
                return _parse_dict(data, pos)
            if 0x30 <= c <= 0x39:
                return _parse_str(data, pos)
            if c == 0x3A:
                raise ValueError("bad_string_length")
            raise ValueError("unexpected_byte")


        def _parse_int(data, pos):
            end = data.find(b"e", pos + 1)
            if end == -1:
                raise ValueError("unexpected_eof")
            body = data[pos + 1:end]
            if not body:
                raise ValueError("bad_int_empty")
            if body == b"-0":
                raise ValueError("bad_int_negative_zero")
            if body[0:1] == b"-":
                rest = body[1:]
                if not rest:
                    raise ValueError("bad_int_format")
                if not all(0x30 <= b <= 0x39 for b in rest):
                    raise ValueError("bad_int_format")
                if len(rest) > 1 and rest[0:1] == b"0":
                    raise ValueError("bad_int_leading_zero")
                return -int(rest.decode("ascii")), end + 1
            if not all(0x30 <= b <= 0x39 for b in body):
                raise ValueError("bad_int_format")
            if len(body) > 1 and body[0:1] == b"0":
                raise ValueError("bad_int_leading_zero")
            return int(body.decode("ascii")), end + 1


        def _parse_str(data, pos):
            colon = data.find(b":", pos)
            if colon == -1:
                raise ValueError("unexpected_eof")
            len_bytes = data[pos:colon]
            if not len_bytes:
                raise ValueError("bad_string_length")
            if not all(0x30 <= b <= 0x39 for b in len_bytes):
                raise ValueError("bad_string_length")
            if len(len_bytes) > 1 and len_bytes[0:1] == b"0":
                raise ValueError("bad_string_length")
            n = int(len_bytes.decode("ascii"))
            start = colon + 1
            if start + n > len(data):
                raise ValueError("bad_string_truncated")
            return data[start:start + n], start + n


        def _parse_list(data, pos):
            items = []
            p = pos + 1
            while True:
                if p >= len(data):
                    raise ValueError("unexpected_eof")
                if data[p] == 0x65:
                    return items, p + 1
                v, p = _parse(data, p)
                items.append(v)


        def _parse_dict(data, pos):
            items = {}
            p = pos + 1
            last_key = None
            while True:
                if p >= len(data):
                    raise ValueError("unexpected_eof")
                if data[p] == 0x65:
                    return items, p + 1
                if not (0x30 <= data[p] <= 0x39):
                    raise ValueError("non_bytes_key")
                k, p = _parse_str(data, p)
                if last_key is not None:
                    if k == last_key:
                        raise ValueError("duplicate_key")
                    if k < last_key:
                        raise ValueError("unsorted_keys")
                if p >= len(data):
                    raise ValueError("unexpected_eof")
                if data[p] == 0x65:
                    raise ValueError("unexpected_eof")
                v, p = _parse(data, p)
                items[k] = v
                last_key = k
    ''')


def _stub_taskF() -> str:
    """Wrong: forgets sorted-keys requirement, accepts leading zeros, uses
    str-typed exception messages, etc.  Will fail many adversarial cases."""
    return textwrap.dedent('''\
        def encode(value):
            if isinstance(value, int) and not isinstance(value, bool):
                return ("i" + str(value) + "e").encode("ascii")
            if isinstance(value, bytes):
                return str(len(value)).encode("ascii") + b":" + value
            if isinstance(value, (list, tuple)):
                out = b"l"
                for item in value:
                    out += encode(item)
                return out + b"e"
            if isinstance(value, dict):
                out = b"d"
                for k, v in value.items():  # not sorted (BUG)
                    out += encode(k) + encode(v)
                return out + b"e"
            raise TypeError("unsupported_type")


        def decode(data):
            if not isinstance(data, (bytes, bytearray)):
                raise TypeError("expected_bytes")
            buf = bytes(data)
            return _p(buf, 0)[0]


        def _p(d, i):
            c = d[i]
            if c == ord("i"):
                e = d.index(b"e", i + 1)
                return int(d[i + 1:e]), e + 1   # accepts leading zeros, etc.
            if c == ord("l"):
                items = []
                p = i + 1
                while d[p] != ord("e"):
                    v, p = _p(d, p)
                    items.append(v)
                return items, p + 1
            if c == ord("d"):
                items = {}
                p = i + 1
                while d[p] != ord("e"):
                    k, p = _p(d, p)
                    v, p = _p(d, p)
                    items[k] = v
                return items, p + 1
            colon = d.index(b":", i)
            n = int(d[i:colon])
            return d[colon + 1:colon + 1 + n], colon + 1 + n
    ''')


# ---------------------------------------------------------------------------
# end TASK F
# ---------------------------------------------------------------------------


# ===========================================================================
# Task registry
# ===========================================================================


@dataclass
class TaskSpec:
    name: str
    bare_text: str
    cases_fn: Callable[[int], list[TestCase]]
    features_fn: Callable[[], list[str]]
    runner_template: str


TASK_REGISTRY: dict[str, TaskSpec] = {
    "semver_compare": TaskSpec(
        name="semver_compare",
        bare_text=TASK_A_BARE_GOAL,
        cases_fn=_gen_taskA_cases,
        features_fn=_features_taskA,
        runner_template=_RUNNER_TASKA,
    ),
    "cidr_v4_coalesce": TaskSpec(
        name="cidr_v4_coalesce",
        bare_text=TASK_B_BARE_GOAL,
        cases_fn=_gen_taskB_cases,
        features_fn=_features_taskB,
        runner_template=_RUNNER_TASKB,
    ),
    "glob_match": TaskSpec(
        name="glob_match",
        bare_text=TASK_C_BARE_GOAL,
        cases_fn=_gen_taskC_cases,
        features_fn=_features_taskC,
        runner_template=_RUNNER_TASKC,
    ),
    "roman_numeral_strict": TaskSpec(
        name="roman_numeral_strict",
        bare_text=TASK_D_BARE_GOAL,
        cases_fn=_gen_taskD_cases,
        features_fn=_features_taskD,
        runner_template=_RUNNER_TASKD,
    ),
    "utf8_strict_codec": TaskSpec(
        name="utf8_strict_codec",
        bare_text=TASK_E_BARE_GOAL,
        cases_fn=_gen_taskE_cases,
        features_fn=_features_taskE,
        runner_template=_RUNNER_TASKE,
    ),
    "bencode_strict_codec": TaskSpec(
        name="bencode_strict_codec",
        bare_text=TASK_F_BARE_GOAL,
        cases_fn=_gen_taskF_cases,
        features_fn=_features_taskF,
        runner_template=_RUNNER_TASKF,
    ),
}


_GOLDEN_FACTORY = {
    "semver_compare": _golden_taskA,
    "cidr_v4_coalesce": _golden_taskB,
    "glob_match": _golden_taskC,
    "roman_numeral_strict": _golden_taskD,
    "utf8_strict_codec": _golden_taskE,
    "bencode_strict_codec": _golden_taskF,
}

_STUB_FACTORY = {
    "semver_compare": _stub_taskA,
    "cidr_v4_coalesce": _stub_taskB,
    "glob_match": _stub_taskC,
    "roman_numeral_strict": _stub_taskD,
    "utf8_strict_codec": _stub_taskE,
    "bencode_strict_codec": _stub_taskF,
}


# ===========================================================================
# Static audit (anti-cheat)
# ===========================================================================


_FORBIDDEN_PATTERNS = [
    r"os\s*\.\s*environ",
    r"\bsubprocess\b", r"\bsocket\b", r"\brequests\b",
    r"\burllib\b", r"\bpathlib\b", r"\bfnmatch\b",
    r"(?<!\.)\bglob\b",
    r"\binspect\b", r"\bipaddress\b", r"\bnetaddr\b",
    r"(?<![.\w])eval\s*\(",
    r"(?<![.\w])exec\s*\(",
    r"(?<![.\w])compile\s*\(",
    r"answer_key", r"expected_output", r"hidden_case",
    r"private_expected", r"META23_PRIVATE", r"scorer_bench_meta",
]


def static_audit_source(source: str) -> tuple[bool, list[str]]:
    hits: list[str] = []
    for pat in _FORBIDDEN_PATTERNS:
        if re.search(pat, source):
            hits.append(pat)
    return (len(hits) == 0), hits


# ===========================================================================
# Generic case-runner
# ===========================================================================


def _values_equal(actual, expected):
    if isinstance(expected, float) and isinstance(actual, (int, float)):
        if math.isnan(expected):
            return isinstance(actual, float) and math.isnan(actual)
        if math.isinf(expected):
            return isinstance(actual, float) and math.isinf(actual) and (
                math.copysign(1.0, actual) == math.copysign(1.0, expected))
        return math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9)
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return False
        return all(_values_equal(a, e) for a, e in zip(actual, expected))
    if isinstance(expected, tuple) and isinstance(actual, (tuple, list)):
        if len(expected) != len(actual):
            return False
        return all(_values_equal(a, e) for a, e in zip(actual, expected))
    if isinstance(expected, dict) and isinstance(actual, dict):
        if set(expected.keys()) != set(actual.keys()):
            return False
        return all(_values_equal(actual[k], expected[k]) for k in expected)
    return actual == expected


def run_solution_against_task(source: str, task: TaskSpec, cases: list[TestCase],
                                workdir: Path) -> ScorerRun:
    workdir.mkdir(parents=True, exist_ok=True)
    src_path = workdir / "solution.py"
    src_path.write_text(source, encoding="utf-8")
    cases_path = workdir / "cases.json"
    write_json(cases_path, [c.as_jsonable() for c in cases])
    out_path = workdir / "results.json"
    runner_path = workdir / "runner.py"
    runner_path.write_text(task.runner_template, encoding="utf-8")

    static_ok, hits = static_audit_source(source)
    if not static_ok:
        return ScorerRun(
            passed=False, score=0.0, passed_cases=0, total_cases=len(cases),
            failed=[{"name": "<static_audit>", "feature": "static_audit",
                     "got_kind": "static_rejected",
                     "got_error": "rejected:" + ",".join(hits[:3])}],
            failed_features=["static_audit"],
            runner_error="static_rejected:" + ",".join(hits[:3]),
            static_rejected=True,
        )

    try:
        proc = subprocess.run(
            [sys.executable, str(runner_path), str(src_path), str(cases_path), str(out_path)],
            cwd=str(workdir), text=True, capture_output=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ScorerRun(
            passed=False, score=0.0, passed_cases=0, total_cases=len(cases),
            failed=[{"name": "<subprocess>", "feature": "subprocess",
                     "got_kind": "subprocess_error",
                     "got_error": str(exc)[:300]}],
            failed_features=["subprocess"],
            runner_error="subprocess_error:" + str(exc)[:300],
        )

    if proc.returncode != 0 or not out_path.exists():
        return ScorerRun(
            passed=False, score=0.0, passed_cases=0, total_cases=len(cases),
            failed=[{"name": "<runner>", "feature": "runner",
                     "got_kind": "runner_error",
                     "got_error": (proc.stderr.strip() or proc.stdout.strip())[:300]}],
            failed_features=["runner"],
            runner_error="runner_exit:" + str(proc.returncode),
        )

    raw = json.loads(out_path.read_text(encoding="utf-8"))
    runner_error = raw.get("runner_error")
    raw_results = raw.get("results", [])

    failed: list[dict[str, Any]] = []
    passed_count = 0
    for case, got in zip(cases, raw_results):
        if case.expected_kind == "value":
            ok = (got.get("got_kind") == "value"
                  and _values_equal(got.get("got_value"), case.expected_value))
        else:
            ok = (got.get("got_kind") == "error"
                  and got.get("got_error") == case.expected_error)
        if ok:
            passed_count += 1
            continue
        failed.append({
            "name": case.name,
            "feature": case.feature,
            "input_repr": case.input_repr,
            "expected_kind": case.expected_kind,
            "expected_value": case.expected_value,
            "expected_error": case.expected_error,
            "got_kind": got.get("got_kind"),
            "got_value_repr": got.get("got_value_repr"),
            "got_value": got.get("got_value"),
            "got_error": got.get("got_error"),
            "got_error_msg": got.get("got_error_msg"),
        })

    score = round(100.0 * passed_count / max(1, len(cases)), 3)
    failed_features = sorted({f["feature"] for f in failed})
    return ScorerRun(
        passed=(passed_count == len(cases)),
        score=score,
        passed_cases=passed_count, total_cases=len(cases),
        failed=failed, failed_features=failed_features,
        runner_error=runner_error,
    )


def harness_truth_score(source: str, task: TaskSpec, seed: int, workdir: Path) -> ScorerRun:
    cases = task.cases_fn(seed)
    return run_solution_against_task(source, task, cases, workdir)


# ===========================================================================
# Builder + Auditor
# ===========================================================================


@dataclass
class BuilderArtifact:
    cases: list[TestCase]
    cases_sha256: str
    builder_seed: int


def builder_synthesise_scorer(task: TaskSpec, seed: int, scorer_dir: Path) -> BuilderArtifact:
    scorer_dir.mkdir(parents=True, exist_ok=True)
    builder_seed = seed + 1000
    cases = task.cases_fn(builder_seed)
    cases_data = [c.as_jsonable() for c in cases]
    write_json(scorer_dir / "cases.json", cases_data)
    digest = sha256_text(stable_json(cases_data))
    (scorer_dir / "synthesis_notes.md").write_text(
        f"# Synthesised scorer for task {task.name}\n\n"
        f"- builder_seed = {builder_seed}\n"
        f"- num_cases    = {len(cases)}\n"
        f"- sha256       = {digest}\n",
        encoding="utf-8",
    )
    return BuilderArtifact(cases=cases, cases_sha256=digest, builder_seed=builder_seed)


@dataclass
class AuditResult:
    passed: bool
    findings: list[dict[str, Any]]


def audit_synthesised_scorer(task: TaskSpec, artifact: BuilderArtifact,
                              audit_dir: Path) -> AuditResult:
    audit_dir.mkdir(parents=True, exist_ok=True)
    findings: list[dict[str, Any]] = []
    golden = _GOLDEN_FACTORY[task.name]()
    pos = run_solution_against_task(golden, task, artifact.cases,
                                      audit_dir / "_pos")
    findings.append({"check": "golden_positive_passes",
                     "passed": pos.passed,
                     "score": pos.score,
                     "details": pos.failed[:3]})
    neg = run_solution_against_task(_STUB_FACTORY[task.name](),
                                      task, artifact.cases,
                                      audit_dir / "_neg")
    findings.append({"check": "stub_negative_fails",
                     "passed": (not neg.passed),
                     "score": neg.score})
    write_json(audit_dir / "findings.json", findings)
    overall = all(f["passed"] for f in findings)
    return AuditResult(passed=overall, findings=findings)


# ===========================================================================
# Local mock actor (offline; used only by self-test for wiring sanity)
# ===========================================================================


def _local_actor_extract_hints(prompt: str, task_name: str) -> dict[str, Any]:
    if "=== FEEDBACK FROM PRIOR ATTEMPT ===" not in prompt:
        return {}
    fb = prompt.split("=== FEEDBACK FROM PRIOR ATTEMPT ===", 1)[1]
    if "your code" not in fb:
        return {}
    return {"task": task_name, "saw_counterexamples": True}


def _local_actor_solution(task: TaskSpec, hints: dict[str, Any]) -> str:
    if not hints.get("saw_counterexamples"):
        return _STUB_FACTORY[task.name]()
    return _GOLDEN_FACTORY[task.name]()


def run_local_actor(prompt: str, task: TaskSpec) -> ActorResult:
    hints = _local_actor_extract_hints(prompt, task.name)
    src = _local_actor_solution(task, hints)
    return ActorResult(
        source=src, raw_response="LOCAL_MOCK",
        prompt_sha256=sha256_text(prompt), response_sha256=sha256_text(src),
        cost_usd=0.0, duration_ms=0, model="local-mock",
    )


# ===========================================================================
# Claude actor invocation
# ===========================================================================


def parse_claude_cost(raw: str) -> float:
    try:
        d = json.loads(raw)
        if isinstance(d, dict):
            v = d.get("total_cost_usd") or d.get("usage", {}).get("total_cost_usd")
            return float(v) if v is not None else 0.0
    except Exception:
        return 0.0
    return 0.0


def parse_claude_duration_ms(raw: str) -> int:
    try:
        d = json.loads(raw)
        if isinstance(d, dict):
            v = d.get("duration_ms")
            return int(v) if v is not None else 0
    except Exception:
        return 0
    return 0


def extract_code_from_response(raw: str) -> str:
    if not raw:
        return ""
    try:
        d = json.loads(raw)
    except Exception:
        return raw
    so = None
    if isinstance(d, dict):
        so = d.get("structured_output")
        if so is None:
            r = d.get("result")
            if isinstance(r, str):
                try:
                    so = json.loads(r)
                except Exception:
                    return r
    if isinstance(so, dict):
        return so.get("code", "")
    return raw


def run_claude_actor(prompt: str, actor_cli: str, model: str,
                      timeout_sec: float, workdir: Path) -> ActorResult:
    schema = {
        "type": "object",
        "properties": {"code": {"type": "string"}},
        "required": ["code"],
        "additionalProperties": False,
    }
    cmd = [
        actor_cli, "--model", model,
        "--effort", "low",
        "--print", "--output-format", "json",
        "--json-schema", stable_json(schema),
        "--system-prompt",
        "You are a non-interactive sealed coding actor. Return ONLY a JSON object matching the requested schema. The 'code' field must contain the complete Python module source for solution.py and nothing else (no markdown fences).",
        "--tools", "",
        "--disable-slash-commands",
        "--no-session-persistence",
        prompt,
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=str(workdir), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout_sec,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ActorResult(
            source="", raw_response="",
            prompt_sha256=sha256_text(prompt),
            response_sha256=sha256_text(str(exc)),
            model=model, error=str(exc),
        )
    raw = proc.stdout.strip()
    if proc.returncode != 0:
        return ActorResult(
            source="", raw_response=raw + "\nSTDERR:\n" + proc.stderr.strip()[:1000],
            prompt_sha256=sha256_text(prompt),
            response_sha256=sha256_text(raw + proc.stderr),
            cost_usd=parse_claude_cost(raw), duration_ms=parse_claude_duration_ms(raw),
            model=model, error=f"claude exit {proc.returncode}",
        )
    return ActorResult(
        source=extract_code_from_response(raw), raw_response=raw,
        prompt_sha256=sha256_text(prompt), response_sha256=sha256_text(raw),
        cost_usd=parse_claude_cost(raw),
        duration_ms=parse_claude_duration_ms(raw),
        model=model,
    )


# ===========================================================================
# Prompt + per-policy feedback
# ===========================================================================


def build_actor_prompt(task: TaskSpec, feedback: list[str], policy: str) -> str:
    parts = [
        "You are implementing a Python module solution.py per the spec below.",
        "Return ONLY a JSON object {\"code\": <complete solution.py source>}.",
        "",
        "=== SPEC ===",
        task.bare_text,
    ]
    if policy == "one_shot":
        return "\n".join(parts)
    if feedback:
        parts.append("")
        parts.append("=== FEEDBACK FROM PRIOR ATTEMPT ===")
        parts.extend(feedback)
        parts.append("")
        parts.append("Please return a corrected complete solution.py.")
    return "\n".join(parts)


def build_feedback_for_policy(policy: str, scorer_run: ScorerRun) -> list[str]:
    if policy == "one_shot":
        return []
    if policy == "r133_bare_goal":
        return [
            f"Your previous attempt passed {scorer_run.passed_cases}/"
            f"{scorer_run.total_cases} hidden cases. The result was not "
            "accepted. Please try again."
        ]
    if policy in ("r38_bare_goal", "candidate_no_counterexample_ablation"):
        if not scorer_run.failed_features:
            return ["Your previous attempt failed; please try again."]
        return [
            "Your previous attempt failed in the following acceptance "
            "categories: " + ", ".join(scorer_run.failed_features) + ".",
            "Please return a corrected solution.",
        ]
    if policy == "candidate":
        out = [
            f"Your previous attempt passed {scorer_run.passed_cases}/"
            f"{scorer_run.total_cases} cases. Specific counterexamples:"
        ]
        seen_features: set[str] = set()
        chosen: list[dict[str, Any]] = []
        for f in scorer_run.failed:
            if f["feature"] in seen_features:
                continue
            seen_features.add(f["feature"])
            chosen.append(f)
            if len(chosen) >= 5:
                break
        for f in scorer_run.failed:
            if len(chosen) >= 5:
                break
            if f not in chosen:
                chosen.append(f)
        for f in chosen:
            inp = f.get("input_repr", "")
            if f.get("expected_kind") == "value":
                ev = f.get("expected_value")
                expected_repr = f"return {ev!r}"
            else:
                expected_repr = f"raise {f.get('expected_error')}"
            if f.get("got_kind") == "value":
                got_repr = f"your code returned {f.get('got_value_repr') or f.get('got_value')!r}"
            elif f.get("got_kind") == "error":
                got_repr = f"your code raised {f.get('got_error')!r}"
                if f.get("got_error_msg"):
                    got_repr += f" ({f.get('got_error_msg')!r})"
            elif f.get("got_kind") == "import_error":
                got_repr = "your code failed to import: " + str(f.get("got_error", ""))[:160]
            elif f.get("got_kind") == "static_rejected":
                got_repr = "your code was statically rejected"
            else:
                got_repr = "your code produced an unexpected result"
            out.append(f"  - input ({inp}) should {expected_repr}; {got_repr}.")
        out.append("Please return a corrected complete solution.py.")
        return out
    raise ValueError(f"unknown policy {policy!r}")


# ===========================================================================
# Per-policy run with caps
# ===========================================================================


@dataclass
class Caps:
    max_rounds: int
    max_calls: int
    wall_clock_cap_sec: float
    timeout_sec: float
    no_progress_patience: int = 2
    repeated_failure_stop: int = 2
    pass_threshold: float = 100.0
    max_total_budget_usd: float = 999.0


def run_policy(policy: str, task: TaskSpec, seed: int, caps: Caps,
                actor_mode: str, actor_cli: str, model: str,
                artifact_dir: Path) -> dict[str, Any]:
    start_wall = time.monotonic()
    policy_dir = artifact_dir / task.name / policy / f"seed_{seed}"
    policy_dir.mkdir(parents=True, exist_ok=True)

    builder_artifact: BuilderArtifact | None = None
    audit: AuditResult | None = None
    if policy in ("candidate", "candidate_no_counterexample_ablation"):
        builder_artifact = builder_synthesise_scorer(task, seed, policy_dir / "_scorer")
        audit = audit_synthesised_scorer(task, builder_artifact, policy_dir / "_audit")

    feedback: list[str] = []
    rounds: list[dict[str, Any]] = []
    total_cost = 0.0
    last_solution: str | None = None
    no_progress = 0
    best_score = -1.0
    consecutive_failures = 0
    effective_max = 1 if policy == "one_shot" else caps.max_calls
    stop_reason = "max_rounds"
    seen_solution_digests: list[str] = []

    for ridx in range(caps.max_rounds):
        if ridx >= effective_max:
            stop_reason = "max_calls"
            break
        elapsed = time.monotonic() - start_wall
        if elapsed >= caps.wall_clock_cap_sec:
            stop_reason = "wall_clock_cap"
            break
        if total_cost >= caps.max_total_budget_usd:
            stop_reason = "cost_cap"
            break

        prompt = build_actor_prompt(task, feedback, policy)
        if actor_mode == "local":
            actor = run_local_actor(prompt, task)
        elif actor_mode == "claude":
            t = min(caps.timeout_sec, max(1.0, caps.wall_clock_cap_sec - elapsed))
            actor = run_claude_actor(prompt, actor_cli, model, t, policy_dir)
        else:
            raise ValueError(f"unknown actor_mode {actor_mode}")

        total_cost += actor.cost_usd
        round_dir = policy_dir / f"round_{ridx + 1}"
        round_dir.mkdir(parents=True, exist_ok=True)
        (round_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
        (round_dir / "raw_response.txt").write_text(actor.raw_response, encoding="utf-8")
        (round_dir / "solution.py").write_text(actor.source, encoding="utf-8")

        if builder_artifact is not None:
            policy_run = run_solution_against_task(
                actor.source, task, builder_artifact.cases,
                round_dir / "_policy_run",
            )
        else:
            policy_run = harness_truth_score(actor.source, task, seed,
                                              round_dir / "_policy_run")

        truth_run = harness_truth_score(actor.source, task, seed,
                                          round_dir / "_truth_run")

        seen_solution_digests.append(sha256_text(actor.source))
        last_solution = actor.source

        write_json(round_dir / "policy_score.json", {
            "passed": policy_run.passed,
            "score": policy_run.score,
            "passed_cases": policy_run.passed_cases,
            "total_cases": policy_run.total_cases,
            "failed_features": policy_run.failed_features,
            "static_rejected": policy_run.static_rejected,
            "runner_error": policy_run.runner_error,
        })
        write_json(round_dir / "trusted_truth_score.json", {
            "passed": truth_run.passed,
            "score": truth_run.score,
            "passed_cases": truth_run.passed_cases,
            "total_cases": truth_run.total_cases,
            "failed_features": truth_run.failed_features,
            "static_rejected": truth_run.static_rejected,
            "runner_error": truth_run.runner_error,
        })

        rounds.append({
            "round": ridx + 1,
            "policy_passed": policy_run.passed,
            "policy_score": policy_run.score,
            "honest_passed": truth_run.passed,
            "honest_score": truth_run.score,
            "passed_cases": truth_run.passed_cases,
            "total_cases": truth_run.total_cases,
            "failed_features": truth_run.failed_features,
            "policy_failed_features": policy_run.failed_features,
            "solution_sha256": seen_solution_digests[-1],
            "prompt_sha256": actor.prompt_sha256,
            "response_sha256": actor.response_sha256,
            "actor_cost_usd": actor.cost_usd,
            "actor_duration_ms": actor.duration_ms,
            "actor_error": actor.error,
        })

        if truth_run.passed:
            stop_reason = "passed_honest"
            break
        if truth_run.score > best_score + 1e-9:
            best_score = truth_run.score
            no_progress = 0
        else:
            no_progress += 1
        consecutive_failures += 1
        if no_progress >= caps.no_progress_patience:
            stop_reason = "no_progress"
            break
        if consecutive_failures >= caps.repeated_failure_stop and ridx + 1 < caps.max_rounds:
            if len(set(seen_solution_digests[-2:])) == 1:
                stop_reason = "repeated_failure_stop"
                break

        feedback = build_feedback_for_policy(policy, policy_run)

    wall = time.monotonic() - start_wall
    return {
        "task": task.name,
        "policy": policy,
        "seed": seed,
        "rounds_used": len(rounds),
        "total_calls": len(rounds),
        "total_cost_usd": total_cost,
        "wall_sec": wall,
        "stop_reason": stop_reason,
        "honest_passed": rounds[-1]["honest_passed"] if rounds else False,
        "honest_score": rounds[-1]["honest_score"] if rounds else 0.0,
        "rounds": rounds,
        "scorer_audit_passed": (audit.passed if audit is not None else None),
        "scorer_audit_findings": (audit.findings if audit is not None else None),
        "builder_seed": (builder_artifact.builder_seed if builder_artifact else None),
        "builder_cases_sha256": (builder_artifact.cases_sha256 if builder_artifact else None),
    }


# ===========================================================================
# Summarize / verdict
# ===========================================================================


def summarize_rows(rows: list[dict[str, Any]], policies: list[str]) -> list[dict[str, Any]]:
    out = []
    for p in policies:
        rs = [r for r in rows if r["policy"] == p]
        if not rs:
            continue
        honest = [1.0 if r["honest_passed"] else 0.0 for r in rs]
        calls = [r["total_calls"] for r in rs]
        wall = [r["wall_sec"] for r in rs]
        cost = [r["total_cost_usd"] for r in rs]
        score = [r["honest_score"] for r in rs]
        stop_reasons = sorted({r["stop_reason"] for r in rs})
        out.append({
            "policy": p,
            "n": len(rs),
            "honest_pass_rate": sum(honest) / len(honest),
            "calls_avg": sum(calls) / len(calls),
            "calls_stdev": stdev_or_zero(calls),
            "wall_avg": sum(wall) / len(wall),
            "wall_stdev": stdev_or_zero(wall),
            "cost_avg": sum(cost) / len(cost),
            "cost_total": sum(cost),
            "score_avg": sum(score) / len(score),
            "stop_reasons": stop_reasons,
        })
    return out


def evaluate_verdict(per_task_summary: dict[str, list[dict[str, Any]]],
                      probe_passing_tasks: list[str],
                      caps: Caps) -> dict[str, Any]:
    out: dict[str, Any] = {
        "selection_passed": bool(probe_passing_tasks),
        "probe_passing_tasks": probe_passing_tasks,
        "strictly_better": False,
        "strictly_better_axis": None,
        "strictly_better_per_task": {},
        "ablation_isolates_counterexamples": False,
        "ablation_axis": None,
        "live_superiority_evidence": False,
    }

    if not probe_passing_tasks:
        out["overall_pass"] = False
        out["explanation"] = "No task survived calibration probe; verdict fail."
        return out

    axes_better_against_r133: dict[str, dict[str, bool]] = {}
    axes_better_against_r38: dict[str, dict[str, bool]] = {}
    axes_better_against_ablation: dict[str, dict[str, bool]] = {}
    for task_name in probe_passing_tasks:
        summary = per_task_summary.get(task_name, [])
        by_pol = {s["policy"]: s for s in summary}
        cand = by_pol.get("candidate")
        r133 = by_pol.get("r133_bare_goal")
        r38 = by_pol.get("r38_bare_goal")
        ablate = by_pol.get("candidate_no_counterexample_ablation")
        if cand is None or r133 is None or r38 is None:
            continue
        a133, a38, aab = {}, {}, {}
        for axis_smaller in ["calls_avg", "wall_avg", "cost_avg"]:
            a133[axis_smaller] = cand[axis_smaller] < r133[axis_smaller] - 1e-6
            a38[axis_smaller] = cand[axis_smaller] < r38[axis_smaller] - 1e-6
            if ablate:
                aab[axis_smaller] = cand[axis_smaller] < ablate[axis_smaller] - 1e-6
        for axis_bigger in ["honest_pass_rate", "score_avg"]:
            a133[axis_bigger] = cand[axis_bigger] > r133[axis_bigger] + 1e-6
            a38[axis_bigger] = cand[axis_bigger] > r38[axis_bigger] + 1e-6
            if ablate:
                aab[axis_bigger] = cand[axis_bigger] > ablate[axis_bigger] + 1e-6
        axes_better_against_r133[task_name] = a133
        axes_better_against_r38[task_name] = a38
        if ablate:
            axes_better_against_ablation[task_name] = aab

    all_axes = ["calls_avg", "wall_avg", "cost_avg", "honest_pass_rate", "score_avg"]
    winning_axis = None
    for axis in all_axes:
        ok = True
        for tn in probe_passing_tasks:
            if tn not in axes_better_against_r133 or tn not in axes_better_against_r38:
                ok = False
                break
            if not (axes_better_against_r133[tn].get(axis) and axes_better_against_r38[tn].get(axis)):
                ok = False
                break
        if ok:
            winning_axis = axis
            break

    out["strictly_better"] = winning_axis is not None
    out["strictly_better_axis"] = winning_axis
    out["strictly_better_per_task"] = {
        tn: {"vs_r133": axes_better_against_r133.get(tn, {}),
             "vs_r38": axes_better_against_r38.get(tn, {})}
        for tn in probe_passing_tasks
    }

    abl_axis = None
    for axis in all_axes:
        ok = True
        for tn in probe_passing_tasks:
            if tn not in axes_better_against_ablation:
                ok = False
                break
            if not axes_better_against_ablation[tn].get(axis):
                ok = False
                break
        if ok and probe_passing_tasks:
            abl_axis = axis
            break
    out["ablation_isolates_counterexamples"] = abl_axis is not None
    out["ablation_axis"] = abl_axis

    out["live_superiority_evidence"] = out["strictly_better"]
    out["overall_pass"] = bool(
        out["selection_passed"]
        and out["strictly_better"]
        and out["ablation_isolates_counterexamples"]
    )
    return out


# ===========================================================================
# CLI entrypoints
# ===========================================================================


def make_caps(args: argparse.Namespace) -> Caps:
    return Caps(
        max_rounds=int(args.max_rounds),
        max_calls=int(args.max_calls),
        wall_clock_cap_sec=float(args.wall_clock_cap_sec),
        timeout_sec=float(args.timeout_sec),
        no_progress_patience=int(args.no_progress_patience),
        repeated_failure_stop=int(args.repeated_failure_stop),
        pass_threshold=float(args.pass_threshold),
        max_total_budget_usd=float(args.max_total_budget_usd),
    )


def run_probe2(args: argparse.Namespace) -> int:
    artifact_dir = Path(args.artifact_dir).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    seeds = [int(s) for s in args.seeds.split(",")]
    task_names = [t for t in args.tasks.split(",") if t]
    for tn in task_names:
        if tn not in TASK_REGISTRY:
            print(f"[probe2] unknown task {tn!r}", file=sys.stderr)
            return 2
    caps = make_caps(args)
    one_shot_caps = Caps(
        max_rounds=1, max_calls=1,
        wall_clock_cap_sec=caps.wall_clock_cap_sec,
        timeout_sec=caps.timeout_sec,
        no_progress_patience=1, repeated_failure_stop=1,
        pass_threshold=caps.pass_threshold,
        max_total_budget_usd=caps.max_total_budget_usd,
    )
    cand_caps = Caps(
        max_rounds=int(args.candidate_max_rounds),
        max_calls=int(args.candidate_max_rounds),
        wall_clock_cap_sec=caps.wall_clock_cap_sec,
        timeout_sec=caps.timeout_sec,
        no_progress_patience=2, repeated_failure_stop=2,
        pass_threshold=caps.pass_threshold,
        max_total_budget_usd=caps.max_total_budget_usd,
    )

    rows_per_task: dict[str, dict[str, list[dict[str, Any]]]] = {}
    total_cost = 0.0
    total_wall_start = time.monotonic()
    skip_cand_when_one_shot_passes = bool(args.skip_candidate_when_one_shot_passes)
    for tn in task_names:
        task = TASK_REGISTRY[tn]
        rows_one = []
        rows_cand = []
        for seed in seeds:
            if total_cost >= caps.max_total_budget_usd:
                break
            r_one = run_policy("one_shot", task, seed, one_shot_caps,
                                args.actor_mode, args.actor_cli, args.model,
                                artifact_dir)
            rows_one.append(r_one)
            total_cost += r_one["total_cost_usd"]
            if total_cost >= caps.max_total_budget_usd:
                rows_cand.append(None)
                continue
            if skip_cand_when_one_shot_passes and r_one["honest_passed"]:
                rows_cand.append({
                    "skipped_because_one_shot_passed": True,
                    "task": tn, "policy": "candidate", "seed": seed,
                    "honest_passed": True,
                    "honest_score": r_one["honest_score"],
                    "total_calls": 0, "total_cost_usd": 0.0,
                    "wall_sec": 0.0, "stop_reason": "skipped_one_shot_passed",
                    "rounds": [], "rounds_used": 0,
                })
                continue
            r_cand = run_policy("candidate", task, seed, cand_caps,
                                 args.actor_mode, args.actor_cli, args.model,
                                 artifact_dir)
            rows_cand.append(r_cand)
            total_cost += r_cand["total_cost_usd"]
        rows_per_task[tn] = {"one_shot": rows_one, "candidate": rows_cand}

    probe_pass_threshold = float(args.probe_pass_threshold)
    candidate_min_pass_rate = float(args.candidate_min_pass_rate)
    selection: dict[str, dict[str, Any]] = {}
    for tn in task_names:
        rows = rows_per_task.get(tn, {"one_shot": [], "candidate": []})
        one = rows["one_shot"]
        cand = [r for r in rows["candidate"] if r is not None]
        one_passed = sum(1 for r in one if r["honest_passed"])
        one_total = len(one)
        cand_passed = sum(1 for r in cand if r["honest_passed"])
        cand_total = len(cand)
        one_rate = one_passed / max(1, one_total)
        cand_rate = cand_passed / max(1, cand_total) if cand_total > 0 else 0.0
        cond_a = one_rate <= probe_pass_threshold
        cond_b = cand_rate >= candidate_min_pass_rate
        selection[tn] = {
            "task": tn,
            "n_seeds_one_shot": one_total,
            "n_seeds_candidate": cand_total,
            "one_shot_pass_rate": one_rate,
            "one_shot_passed": one_passed,
            "candidate_pass_rate": cand_rate,
            "candidate_passed": cand_passed,
            "probe_pass_threshold_max": probe_pass_threshold,
            "candidate_min_pass_rate": candidate_min_pass_rate,
            "calibrated_one_shot_below_thresh": cond_a,
            "calibrated_candidate_above_thresh": cond_b,
            "calibrated_overall": cond_a and cond_b,
        }
    probe_passing_tasks = [tn for tn, s in selection.items() if s["calibrated_overall"]]

    out = {
        "kind": "probe2",
        "actor_mode": args.actor_mode,
        "model": args.model,
        "seeds": seeds,
        "tasks": task_names,
        "selection": selection,
        "probe_passing_tasks": probe_passing_tasks,
        "rows_per_task": rows_per_task,
        "total_cost_usd": total_cost,
        "wall_sec": time.monotonic() - total_wall_start,
        "caps": {"one_shot": asdict(one_shot_caps),
                  "candidate": asdict(cand_caps)},
    }
    if args.out:
        write_json(Path(args.out), out)
    public = {k: v for k, v in out.items() if k != "rows_per_task"}
    print(pretty_json(public))
    return 0 if probe_passing_tasks else 3


def run_compare(args: argparse.Namespace) -> int:
    artifact_dir = Path(args.artifact_dir).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    seeds = [int(s) for s in args.seeds.split(",")]
    policies = [p for p in args.policies.split(",") if p]
    task_names = [t for t in args.task.split(",") if t]
    for tn in task_names:
        if tn not in TASK_REGISTRY:
            print(f"[compare] unknown task {tn!r}", file=sys.stderr)
            return 2
    caps = make_caps(args)

    per_task_rows: dict[str, list[dict[str, Any]]] = {}
    total_cost = 0.0
    total_wall_start = time.monotonic()
    for tn in task_names:
        task = TASK_REGISTRY[tn]
        rows = []
        for policy in policies:
            for seed in seeds:
                r = run_policy(policy, task, seed, caps,
                                args.actor_mode, args.actor_cli, args.model,
                                artifact_dir)
                rows.append(r)
                total_cost += r["total_cost_usd"]
                if total_cost >= caps.max_total_budget_usd:
                    print(f"[compare] hit max_total_budget_usd={caps.max_total_budget_usd}",
                          file=sys.stderr)
                    break
            if total_cost >= caps.max_total_budget_usd:
                break
        per_task_rows[tn] = rows
        if total_cost >= caps.max_total_budget_usd:
            break

    per_task_summary = {tn: summarize_rows(rows, policies)
                         for tn, rows in per_task_rows.items()}

    probe_passing_tasks = list(per_task_rows.keys())
    verdict = evaluate_verdict(per_task_summary, probe_passing_tasks, caps)

    out = {
        "kind": "compare",
        "actor_mode": args.actor_mode,
        "model": args.model,
        "seeds": seeds,
        "policies": policies,
        "tasks": task_names,
        "per_task_summary": per_task_summary,
        "per_task_rows": per_task_rows,
        "verdict": verdict,
        "total_cost_usd": total_cost,
        "wall_sec": time.monotonic() - total_wall_start,
        "caps": asdict(caps),
    }
    if args.out:
        write_json(Path(args.out), out)
    public = {k: v for k, v in out.items() if k != "per_task_rows"}
    print(pretty_json(public))
    return 0 if verdict["overall_pass"] else 3


def run_self_test(args: argparse.Namespace) -> int:
    workdir = Path(args.artifact_dir or "/tmp/r13_selftest_art").resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    for tn, task in TASK_REGISTRY.items():
        cases = task.cases_fn(7)
        check(f"{tn}_has_cases", len(cases) >= 25,
              f"got {len(cases)} cases")
        feats = task.features_fn()
        case_feats = {c.feature for c in cases}
        check(f"{tn}_features_cover_cases",
              case_feats.issubset(set(feats)),
              f"unknown_in_cases={case_feats - set(feats)}")

    for tn, task in TASK_REGISTRY.items():
        cases = task.cases_fn(7)
        golden = _GOLDEN_FACTORY[tn]()
        run = run_solution_against_task(golden, task, cases,
                                          workdir / f"_gold_{tn}")
        check(f"{tn}_golden_passes", run.passed,
              f"score={run.score} failed_features={run.failed_features[:5]}")

    for tn, task in TASK_REGISTRY.items():
        cases = task.cases_fn(7)
        stub = _STUB_FACTORY[tn]()
        run = run_solution_against_task(stub, task, cases,
                                          workdir / f"_stub_{tn}")
        check(f"{tn}_stub_fails", not run.passed,
              f"score={run.score}")

    bad_src = "import os\nx = os.environ.get('X')\n"
    ok, hits = static_audit_source(bad_src)
    check("static_audit_blocks_os_environ", (not ok) and any("os" in h for h in hits))
    bad_src2 = "y = eval('1+1')\n"
    ok2, hits2 = static_audit_source(bad_src2)
    check("static_audit_blocks_eval", (not ok2) and any("eval" in h for h in hits2))
    bad_src3 = "import ipaddress\nx = ipaddress.ip_network('1/8')\n"
    ok3, hits3 = static_audit_source(bad_src3)
    check("static_audit_blocks_ipaddress", (not ok3) and any("ipaddress" in h for h in hits3))
    bad_src4 = "import fnmatch\nx = fnmatch.fnmatch('a', 'b')\n"
    ok4, hits4 = static_audit_source(bad_src4)
    check("static_audit_blocks_fnmatch", (not ok4) and any("fnmatch" in h for h in hits4))
    good_src = "def f(x):\n    return x + 1\n"
    okg, _ = static_audit_source(good_src)
    check("static_audit_passes_clean", okg)
    re_src = "import re\np = re.compile('a')\n"
    okr, _ = static_audit_source(re_src)
    check("static_audit_allows_re_compile", okr)

    for tn, task in TASK_REGISTRY.items():
        ba = builder_synthesise_scorer(task, 7, workdir / f"_build_{tn}")
        check(f"{tn}_builder_emits_cases", len(ba.cases) >= 25)
        au = audit_synthesised_scorer(task, ba, workdir / f"_audit_{tn}")
        check(f"{tn}_auditor_passes", au.passed,
              f"findings={au.findings}")

    for tn, task in TASK_REGISTRY.items():
        bare_prompt = build_actor_prompt(task, [], "one_shot")
        hints = _local_actor_extract_hints(bare_prompt, tn)
        check(f"{tn}_bare_goal_no_hints", not hints,
              f"hints={hints}")
        r38_prompt = build_actor_prompt(
            task, build_feedback_for_policy("r38_bare_goal",
                ScorerRun(passed=False, score=0.0, passed_cases=0, total_cases=10,
                          failed_features=["randomized_compare"])),
            "r38_bare_goal")
        hints = _local_actor_extract_hints(r38_prompt, tn)
        check(f"{tn}_property_name_only_does_not_lift_local_actor",
              not hints, f"hints={hints}")
        cand_fb = ScorerRun(
            passed=False, score=0.0, passed_cases=0, total_cases=10,
            failed=[{
                "name": "demo", "feature": "demo",
                "input_repr": "input X",
                "expected_kind": "value", "expected_value": 1,
                "got_kind": "value", "got_value_repr": "0",
                "got_value": 0,
            }],
            failed_features=["demo"])
        cand_prompt = build_actor_prompt(
            task, build_feedback_for_policy("candidate", cand_fb),
            "candidate")
        hints = _local_actor_extract_hints(cand_prompt, tn)
        check(f"{tn}_candidate_counterexample_lifts_local_actor",
              bool(hints.get("saw_counterexamples")),
              f"hints={hints}")

    caps = Caps(max_rounds=4, max_calls=4, wall_clock_cap_sec=300,
                 timeout_sec=10, no_progress_patience=2,
                 repeated_failure_stop=2, pass_threshold=100.0,
                 max_total_budget_usd=999)
    for tn in TASK_REGISTRY:
        task = TASK_REGISTRY[tn]
        rows = []
        for policy in ["one_shot", "r38_bare_goal", "candidate"]:
            r = run_policy(policy, task, 7, caps, "local", "", "",
                            workdir / f"_local_{tn}")
            rows.append(r)
        check(f"{tn}_local_oneshot_fails",
              rows[0]["honest_passed"] is False,
              f"oneshot honest_score={rows[0]['honest_score']}")
        check(f"{tn}_local_candidate_eventually_passes",
              rows[2]["honest_passed"],
              f"cand stop={rows[2]['stop_reason']} score={rows[2]['honest_score']}")
        check(f"{tn}_local_r38_remains_failed",
              rows[1]["honest_passed"] is False,
              f"r38 stop={rows[1]['stop_reason']} score={rows[1]['honest_score']}")

    for tn in TASK_REGISTRY:
        task = TASK_REGISTRY[tn]
        for policy in ["one_shot", "r133_bare_goal", "r38_bare_goal",
                       "candidate", "candidate_no_counterexample_ablation"]:
            p = build_actor_prompt(task, [], policy)
            for forbidden in ("answer_key", "expected_output", "META23_PRIVATE",
                              "scorer_bench_meta", "private_expected"):
                check(f"{tn}_{policy}_prompt_clean_{forbidden}",
                      forbidden not in p,
                      f"found {forbidden!r}")

    import inspect as _inspect
    src = _inspect.getsource(run_claude_actor)
    check("claude_no_max_budget_flag", "--max-budget-usd" not in src,
          "claude cmd must not contain --max-budget-usd")

    a_goal = TASK_A_BARE_GOAL
    check("taskA_goal_mentions_compare", "compare" in a_goal)
    check("taskA_goal_mentions_invalid_version", "invalid_version" in a_goal)
    check("taskA_goal_mentions_semver", "Semantic Versioning" in a_goal)

    b_goal = TASK_B_BARE_GOAL
    check("taskB_goal_mentions_coalesce", "coalesce" in b_goal)
    check("taskB_goal_mentions_invalid_cidr", "invalid_cidr" in b_goal)
    check("taskB_goal_mentions_no_ipaddress", "ipaddress" in b_goal)

    c_goal = TASK_C_BARE_GOAL
    check("taskC_goal_mentions_match", "def match" in c_goal)
    check("taskC_goal_mentions_doublestar", "**" in c_goal)
    check("taskC_goal_mentions_bad_pattern", "bad_pattern" in c_goal)
    check("taskC_goal_forbids_fnmatch", "fnmatch" in c_goal)

    d_goal = TASK_D_BARE_GOAL
    check("taskD_goal_mentions_render", "def render" in d_goal)
    check("taskD_goal_mentions_parse", "def parse" in d_goal)
    check("taskD_goal_mentions_invalid_roman", "invalid_roman" in d_goal)
    check("taskD_goal_mentions_out_of_range", "out_of_range" in d_goal)

    e_goal = TASK_E_BARE_GOAL
    check("taskE_goal_mentions_encode", "def encode" in e_goal)
    check("taskE_goal_mentions_decode", "def decode" in e_goal)
    check("taskE_goal_mentions_overlong", "overlong" in e_goal)
    check("taskE_goal_mentions_surrogate", "surrogate_codepoint" in e_goal)
    check("taskE_goal_mentions_out_of_range", "out_of_range_codepoint" in e_goal)
    check("taskE_goal_mentions_truncated", "truncated" in e_goal)
    check("taskE_goal_mentions_orphan_continuation",
          "orphan_continuation" in e_goal)
    check("taskE_goal_forbids_str_encode", "do NOT use" in e_goal
          and "str.encode" in e_goal)

    f_goal = TASK_F_BARE_GOAL
    check("taskF_goal_mentions_encode", "def encode" in f_goal)
    check("taskF_goal_mentions_decode", "def decode" in f_goal)
    check("taskF_goal_mentions_unsupported_type", "unsupported_type" in f_goal)
    check("taskF_goal_mentions_non_bytes_key", "non_bytes_key" in f_goal)
    check("taskF_goal_mentions_unsorted_keys", "unsorted_keys" in f_goal)
    check("taskF_goal_mentions_duplicate_key", "duplicate_key" in f_goal)
    check("taskF_goal_mentions_trailing_bytes", "trailing_bytes" in f_goal)
    check("taskF_goal_mentions_bad_int_leading_zero",
          "bad_int_leading_zero" in f_goal)
    check("taskF_goal_mentions_bad_int_negative_zero",
          "bad_int_negative_zero" in f_goal)
    check("taskF_goal_mentions_bad_string_length",
          "bad_string_length" in f_goal)
    check("taskF_goal_mentions_bad_string_truncated",
          "bad_string_truncated" in f_goal)
    check("taskF_goal_mentions_unexpected_eof", "unexpected_eof" in f_goal)
    check("taskF_goal_mentions_unexpected_byte", "unexpected_byte" in f_goal)
    check("taskF_goal_mentions_bool_subclass", "bool is a subclass" in f_goal)
    check("taskF_goal_mentions_sorted_keys", "sorted" in f_goal)
    check("taskF_goal_mentions_round_trip",
          "ROUND-TRIP INVARIANT" in f_goal or "round-trip" in f_goal.lower())
    check("taskF_goal_forbids_third_party_bencode",
          "bencode" in f_goal and "DO NOT" in f_goal)
    check("taskF_features_includes_random_roundtrip",
          "random_roundtrip_encode" in TASK_REGISTRY["bencode_strict_codec"].features_fn()
          and "random_roundtrip_decode" in TASK_REGISTRY["bencode_strict_codec"].features_fn())
    check("taskF_cases_at_least_300",
          len(TASK_REGISTRY["bencode_strict_codec"].cases_fn(7)) >= 300,
          f"got {len(TASK_REGISTRY['bencode_strict_codec'].cases_fn(7))}")

    overall = all(c["ok"] for c in checks)
    out = {
        "kind": "self_test",
        "passed": overall,
        "n_checks": len(checks),
        "n_failed": sum(1 for c in checks if not c["ok"]),
        "checks": checks,
    }
    if args.out:
        write_json(Path(args.out), out)
    print(pretty_json({"passed": overall,
                        "n_checks": len(checks),
                        "n_failed": out["n_failed"],
                        "failed": [c for c in checks if not c["ok"]][:20]}))
    return 0 if overall else 3


def emit_package(args: argparse.Namespace) -> int:
    pkg = {
        "name": "scorer_bench_meta_r13_candidate",
        "version": 13,
        "description": ("Round 13 — r12 harness verbatim + new TASK_F "
                         "bencode_strict_codec (~327 cases/seed: ~87 fixed "
                         "adversarial + 240 randomized round-trip); compare "
                         "ladder ALWAYS executed even when probe gate fails, "
                         "so the saturation tie itself is documented with "
                         "real numbers per Composer r12 feedback."),
        "tasks": list(TASK_REGISTRY.keys()),
        "policies": [
            "one_shot", "r133_bare_goal", "r38_bare_goal",
            "candidate", "candidate_no_counterexample_ablation",
        ],
        "canonical_commands": {
            "self_test": (
                "python3 code.py --self-test "
                "--out /tmp/r13_selftest.json --artifact-dir /tmp/r13_selftest_art"
            ),
            "calibration_probe2_only_taskF": (
                "python3 code.py --probe2 --actor-mode claude "
                "--actor-cli claude --model claude-opus-4-7 "
                "--tasks bencode_strict_codec "
                "--seeds 95,96,97 --max-rounds 1 --max-calls 1 "
                "--candidate-max-rounds 5 "
                "--probe-pass-threshold 0.50 --candidate-min-pass-rate 0.50 "
                "--timeout-sec 240 --wall-clock-cap-sec 1800 "
                "--max-total-budget-usd 4 "
                "--skip-candidate-when-one-shot-passes "
                "--out /tmp/r13_probe2.json --artifact-dir /tmp/r13_probe2_art"
            ),
            "live_compare_taskF_5policy": (
                "python3 code.py --compare-baseline --actor-mode claude "
                "--actor-cli claude --model claude-opus-4-7 "
                "--task bencode_strict_codec "
                "--policies one_shot,r133_bare_goal,r38_bare_goal,candidate,candidate_no_counterexample_ablation "
                "--seeds 95,96 --max-rounds 4 --max-calls 4 "
                "--timeout-sec 240 --wall-clock-cap-sec 3600 "
                "--max-total-budget-usd 8 "
                "--out /tmp/r13_live.json --artifact-dir /tmp/r13_live_art"
            ),
        },
    }
    if args.out:
        write_json(Path(args.out), pkg)
    print(pretty_json(pkg))
    return 0


# ===========================================================================
# Argparse
# ===========================================================================


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="r13 calibrated nontrivial task ladder + bencode_strict_codec")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--probe2", action="store_true")
    mode.add_argument("--compare-baseline", action="store_true")
    mode.add_argument("--emit-package", action="store_true")

    p.add_argument("--tasks", default=",".join(TASK_REGISTRY.keys()))
    p.add_argument("--task", default="")
    p.add_argument("--policies",
                    default="one_shot,r133_bare_goal,r38_bare_goal,candidate,candidate_no_counterexample_ablation")

    p.add_argument("--actor-mode", choices=["local", "claude"], default="local")
    p.add_argument("--actor-cli", default="claude")
    p.add_argument("--model", default="claude-opus-4-7")

    p.add_argument("--seeds", default="90,91,92")
    p.add_argument("--max-rounds", default=4, type=int)
    p.add_argument("--max-calls", default=4, type=int)
    p.add_argument("--candidate-max-rounds", default=5, type=int)
    p.add_argument("--timeout-sec", default=240, type=float)
    p.add_argument("--wall-clock-cap-sec", default=1800, type=float)
    p.add_argument("--no-progress-patience", default=2, type=int)
    p.add_argument("--repeated-failure-stop", default=2, type=int)
    p.add_argument("--pass-threshold", default=100.0, type=float)
    p.add_argument("--max-total-budget-usd", default=20.0, type=float)
    p.add_argument("--probe-pass-threshold", default=0.50, type=float)
    p.add_argument("--candidate-min-pass-rate", default=0.50, type=float)
    p.add_argument("--skip-candidate-when-one-shot-passes",
                    action="store_true", default=False)

    p.add_argument("--out", default="")
    p.add_argument("--artifact-dir", default="/tmp/r13_artifacts")

    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.self_test:
        return run_self_test(args)
    if args.probe2:
        return run_probe2(args)
    if args.compare_baseline:
        if not args.task:
            print("[compare] --task is required", file=sys.stderr)
            return 2
        return run_compare(args)
    if args.emit_package:
        return emit_package(args)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
