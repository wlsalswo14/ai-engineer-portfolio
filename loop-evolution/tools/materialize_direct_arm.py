from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
sys.path.insert(0, str(SOURCE))

from loop_evolution.common import atomic_json, content_hash  # noqa: E402


POSITION_START = """    @classmethod
    def start(cls):
        return cls.fen('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1')
"""

POSITION_NORMAL_FORM = """    @classmethod
    def start(cls):
        return cls.fen('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1')
    def key(self):
        # One canonical state identity shared by search and transposition consumers.
        return (''.join(self.b),self.side,self.cast,self.ep)
"""

SEARCH_PREFIX = """        ms=legal(p)
        if not ms:return -MATE+ply if attacked(p,king(p,p.side),p.side^1) else 0
        ms.sort(key=lambda m:self.mscore(p,m,tt,ply),reverse=True);best=-INF;bestm=ms[0]
        for m in ms:
            q=make(p,m);nd=depth-1
            if depth<=2 and attacked(q,king(q,q.side),q.side^1):nd+=1
            sc=-self.search(q,nd,-beta,-alpha,ply+1)
            if sc>best:best=sc;bestm=m
            if sc>alpha:alpha=sc
            if alpha>=beta:
"""

SEARCH_PVS_LMR = """        checked=attacked(p,king(p,p.side),p.side^1);ms=legal(p)
        if not ms:return -MATE+ply if checked else 0
        ms.sort(key=lambda m:self.mscore(p,m,tt,ply),reverse=True);best=-INF;bestm=ms[0]
        for index,m in enumerate(ms):
            q=make(p,m);gives_check=attacked(q,king(q,q.side),q.side^1);nd=depth-1
            if depth<=2 and gives_check:nd+=1
            a=m&63;z=(m>>6)&63;pr=(m>>12)&15;fl=m>>16
            quiet=p.b[z]=='.' and not (fl&2) and not pr
            reduction=1 if index>=4 and depth>=3 and not checked and not gives_check and quiet and m!=tt else 0
            if index==0:
                sc=-self.search(q,nd,-beta,-alpha,ply+1)
            else:
                sc=-self.search(q,max(0,nd-reduction),-alpha-1,-alpha,ply+1)
                if sc>alpha:
                    sc=-self.search(q,nd,-beta,-alpha,ply+1)
            if sc>best:best=sc;bestm=m
            if sc>alpha:alpha=sc
            if alpha>=beta:
"""

SEARCH_PVS = """        checked=attacked(p,king(p,p.side),p.side^1);ms=legal(p)
        if not ms:return -MATE+ply if checked else 0
        ms.sort(key=lambda m:self.mscore(p,m,tt,ply),reverse=True);best=-INF;bestm=ms[0]
        for index,m in enumerate(ms):
            q=make(p,m);nd=depth-1
            if depth<=2 and attacked(q,king(q,q.side),q.side^1):nd+=1
            if index==0:
                sc=-self.search(q,nd,-beta,-alpha,ply+1)
            else:
                sc=-self.search(q,nd,-alpha-1,-alpha,ply+1)
                if sc>alpha:
                    sc=-self.search(q,nd,-beta,-alpha,ply+1)
            if sc>best:best=sc;bestm=m
            if sc>alpha:alpha=sc
            if alpha>=beta:
"""

NULL_MOVE_HELPER = """def nullmove(p):
    # Search-only reversible state transition: no board mutation, no stale EP.
    return Position(p.b[:],p.side^1,p.cast,-1,p.half+1,p.full+(1 if p.side else 0))

"""

NULL_MOVE_FRONTIER = """        checked=attacked(p,king(p,p.side),p.side^1)
        has_non_pawn_material=any(pc!='.' and pc.isupper()==(p.side==0) and pc.lower() not in ('p','k') for pc in p.b)
        if allow_null and depth>=4 and has_non_pawn_material and -MATE+1000<beta<MATE-1000:
            null_reduction=2+depth//6
            sc=-self.search(nullmove(p),max(0,depth-1-null_reduction),-beta,-beta+1,ply+1,False)
            if sc>=beta:return sc
        ms=legal(p)
"""

ROOT_SEARCH = """    def root(self,p,ms,depth):
        ms=ms[:];ms.sort(key=lambda m:self.mscore(p,m,-1,0),reverse=True)
        alpha=-INF;best=-INF;bm=ms[0]
        for m in ms:
            self.check_time();sc=-self.search(make(p,m),depth-1,-INF,-alpha,1)
            if sc>best:best=sc;bm=m
            if sc>alpha:alpha=sc
        return best,bm
"""

ROOT_WINDOWED_SEARCH = """    def root(self,p,ms,depth,alpha=-INF,beta=INF):
        ms=ms[:];ms.sort(key=lambda m:self.mscore(p,m,-1,0),reverse=True)
        best=-INF;bm=ms[0]
        for index,m in enumerate(ms):
            self.check_time();q=make(p,m)
            if index==0:
                sc=-self.search(q,depth-1,-beta,-alpha,1)
            else:
                sc=-self.search(q,depth-1,-alpha-1,-alpha,1)
                if sc>alpha:sc=-self.search(q,depth-1,-beta,-alpha,1)
            if sc>best:best=sc;bm=m
            if sc>alpha:alpha=sc
            if alpha>=beta:break
        return best,bm
"""

ROOT_HINT_SEARCH = """    def root(self,p,ms,depth,hint=-1):
        ms=ms[:];ms.sort(key=lambda m:(m==hint,self.mscore(p,m,-1,0)),reverse=True)
        alpha=-INF;best=-INF;bm=ms[0]
        for m in ms:
            self.check_time();sc=-self.search(make(p,m),depth-1,-INF,-alpha,1)
            if sc>best:best=sc;bm=m
            if sc>alpha:alpha=sc
        return best,bm
"""

ITERATIVE_DEEPENING = """        self.nodes=0;self.deadline=time.perf_counter()+max(0.001,millis/1000.0*0.82)
        for depth in range(1,64):
            try:score,m=self.root(self.pos,moves,depth)
            except TimeoutError:break
            best=m
            if abs(score)>MATE-1000:break
"""

ASPIRATION_ITERATIVE_DEEPENING = """        self.nodes=0;self.deadline=time.perf_counter()+max(0.001,millis/1000.0*0.82);last_score=0
        for depth in range(1,64):
            try:
                if depth<4:score,m=self.root(self.pos,moves,depth)
                else:
                    window=50;lo=last_score-window;hi=last_score+window
                    score,m=self.root(self.pos,moves,depth,lo,hi)
                    if score<=lo or score>=hi:score,m=self.root(self.pos,moves,depth)
            except TimeoutError:break
            best=m;last_score=score
            moves=[best]+[move for move in moves if move!=best]
            if abs(score)>MATE-1000:break
"""

PV_HINT_ITERATIVE_DEEPENING = """        self.nodes=0;self.deadline=time.perf_counter()+max(0.001,millis/1000.0*0.82);hint=-1
        for depth in range(1,64):
            try:score,m=self.root(self.pos,moves,depth,hint)
            except TimeoutError:break
            best=m;hint=m
            if abs(score)>MATE-1000:break
"""

TT_MATE_INVARIANT = "# NORMAL_FORM_INVARIANT: TT mate scores must preserve root-relative distance across probe ply.\n\n"

TT_MATE_HELPERS = """def score_to_tt(score,ply):
    if score>MATE-1000:return score+ply
    if score<-MATE+1000:return score-ply
    return score

def score_from_tt(score,ply):
    if score>MATE-1000:return score-ply
    if score<-MATE+1000:return score+ply
    return score

"""

LEGAL_FUNCTION = """def legal(p,captures=False):
    out=[];side=p.side
    for m in pseudo(p,captures):
        q=make(p,m)
        if not attacked(q,king(q,side),side^1):out.append(m)
    return out
"""

LEGAL_CHILDREN_FUNCTION = """def legal_children(p,captures=False):
    out=[];side=p.side
    for m in pseudo(p,captures):
        q=make(p,m)
        if not attacked(q,king(q,side),side^1):out.append((m,q))
    return out

def legal(p,captures=False):
    return [m for m,q in legal_children(p,captures)]
"""

KING_SCAN_FUNCTION = """def king(p,side):
    k='K' if side==0 else 'k'
    for i,x in enumerate(p.b):
        if x==k:return i
    return -1
"""

KING_CACHE_FUNCTION = """def king(p,side):
    return p.wk if side==0 else p.bk
"""

POSITION_INIT = """class Position:
    def __init__(self,b,side,cast,ep,half,full):
        self.b=b;self.side=side;self.cast=cast;self.ep=ep;self.half=half;self.full=full
"""

POSITION_KING_CACHE_INIT = """class Position:
    def __init__(self,b,side,cast,ep,half,full,wk=None,bk=None):
        self.b=b;self.side=side;self.cast=cast;self.ep=ep;self.half=half;self.full=full
        self.wk=next((i for i,x in enumerate(b) if x=='K'),-1) if wk is None else wk
        self.bk=next((i for i,x in enumerate(b) if x=='k'),-1) if bk is None else bk
"""

POSITION_RETURN = """    return Position(b,p.side^1,c,ep,0 if pc.lower()=='p' or cap!='.' else p.half+1,p.full+(1 if p.side else 0))
"""

POSITION_KING_CACHE_RETURN = """    return Position(b,p.side^1,c,ep,0 if pc.lower()=='p' or cap!='.' else p.half+1,p.full+(1 if p.side else 0),z if pc=='K' else p.wk,z if pc=='k' else p.bk)
"""

QSEARCH_LEGAL_FLOW = """        if ply>=12:
            ms=legal(p,False)
            if not ms:return -MATE+ply if checked else 0
            return self.evaluate(p)
        stand=-INF
        if not checked:
            stand=self.evaluate(p)
            if stand>=beta:return stand
            if stand>alpha:alpha=stand
        ms=legal(p,False if checked else True)
        if not ms:return -MATE+ply if checked else stand
        ms.sort(key=lambda m:self.mscore(p,m,-1,ply),reverse=True)
        for m in ms:
            sc=-self.qsearch(make(p,m),-beta,-alpha,ply+1)
"""

QSEARCH_CHILD_FLOW = """        if ply>=12:
            children=legal_children(p,False)
            if not children:return -MATE+ply if checked else 0
            return self.evaluate(p)
        stand=-INF
        if not checked:
            stand=self.evaluate(p)
            if stand>=beta:return stand
            if stand>alpha:alpha=stand
        children=legal_children(p,False if checked else True)
        if not children:return -MATE+ply if checked else stand
        children.sort(key=lambda item:self.mscore(p,item[0],-1,ply),reverse=True)
        for m,q in children:
            sc=-self.qsearch(q,-beta,-alpha,ply+1)
"""

SEARCH_LEGAL_FLOW = """        checked=attacked(p,king(p,p.side),p.side^1);ms=legal(p)
        if not ms:return -MATE+ply if checked else 0
        ms.sort(key=lambda m:self.mscore(p,m,tt,ply),reverse=True);best=-INF;bestm=ms[0]
        for index,m in enumerate(ms):
            q=make(p,m);gives_check=attacked(q,king(q,q.side),q.side^1);nd=depth-1
"""

SEARCH_CHILD_FLOW = """        checked=attacked(p,king(p,p.side),p.side^1);children=legal_children(p)
        if not children:return -MATE+ply if checked else 0
        children.sort(key=lambda item:self.mscore(p,item[0],tt,ply),reverse=True);best=-INF;bestm=children[0][0]
        for index,(m,q) in enumerate(children):
            gives_check=attacked(q,king(q,q.side),q.side^1);nd=depth-1
"""

ROOT_CHILD_SEARCH = """    def root(self,p,children,depth):
        children=children[:];children.sort(key=lambda item:self.mscore(p,item[0],-1,0),reverse=True)
        alpha=-INF;best=-INF;bm=children[0][0]
        for m,q in children:
            self.check_time();sc=-self.search(q,depth-1,-INF,-alpha,1)
            if sc>best:best=sc;bm=m
            if sc>alpha:alpha=sc
        return best,bm
"""


def _replace_once(source: str, before: str, after: str, label: str) -> str:
    count = source.count(before)
    if count != 1:
        raise RuntimeError(f"{label} expected exactly once, found {count}")
    return source.replace(before, after, 1)


def normalize_source(anchor: str) -> str:
    # A promoted engine can already carry the champion's normal form.  In that
    # case the next round must consume it as-is instead of duplicating the seam.
    already_normalized = POSITION_NORMAL_FORM in anchor and "key=p.key();" in anchor
    if already_normalized:
        if "key=(''.join(p.b),p.side,p.cast,p.ep);" in anchor:
            raise RuntimeError("mixed canonical and legacy transposition key seams")
        return anchor
    source = _replace_once(anchor, POSITION_START, POSITION_NORMAL_FORM, "Position.start seam")
    return _replace_once(
        source,
        "key=(''.join(p.b),p.side,p.cast,p.ep);orig=alpha;oldbeta=beta;ent=self.tt.get(key);tt=-1",
        "key=p.key();orig=alpha;oldbeta=beta;ent=self.tt.get(key);tt=-1",
        "transposition key seam",
    )


def strengthen_source(normalized: str) -> str:
    if SEARCH_PVS_LMR in normalized:
        return normalized
    return _replace_once(normalized, SEARCH_PREFIX, SEARCH_PVS_LMR, "search traversal seam")


def provisional_source(normalized: str) -> str:
    if SEARCH_PVS_LMR in normalized or SEARCH_PVS in normalized:
        return normalized
    return _replace_once(normalized, SEARCH_PREFIX, SEARCH_PVS, "search traversal seam")


def frontier_strength_source(strengthened: str) -> str:
    """Add one bounded, dependency-complete null-move search frontier."""
    markers = (
        "def nullmove(p):",
        "def search(self,p,depth,alpha,beta,ply,allow_null=True):",
        "if allow_null and depth>=4 and has_non_pawn_material",
    )
    if all(marker in strengthened for marker in markers):
        return strengthened
    if any(marker in strengthened for marker in markers):
        raise RuntimeError("partial null-move frontier detected")
    source = _replace_once(
        strengthened,
        "def legal(p,captures=False):",
        NULL_MOVE_HELPER + "def legal(p,captures=False):",
        "null-move state transition seam",
    )
    source = _replace_once(
        source,
        "    def search(self,p,depth,alpha,beta,ply):",
        "    def search(self,p,depth,alpha,beta,ply,allow_null=True):",
        "search null-permission seam",
    )
    return _replace_once(
        source,
        "        checked=attacked(p,king(p,p.side),p.side^1);ms=legal(p)\n"
        "        if not ms:return -MATE+ply if checked else 0\n",
        NULL_MOVE_FRONTIER + "        if not ms:return -MATE+ply if checked else 0\n",
        "frontier-scoped null-move pruning seam",
    )


def aspiration_root_source(strengthened: str) -> str:
    """Precommit one root-window efficiency target and discharge it once."""
    markers = (
        "def root(self,p,ms,depth,alpha=-INF,beta=INF):",
        "window=50;lo=last_score-window;hi=last_score+window",
        "moves=[best]+[move for move in moves if move!=best]",
    )
    if all(marker in strengthened for marker in markers):
        return strengthened
    if any(marker in strengthened for marker in markers):
        raise RuntimeError("partial aspiration-root frontier detected")
    source = _replace_once(
        strengthened,
        ROOT_SEARCH,
        ROOT_WINDOWED_SEARCH,
        "root window-control seam",
    )
    return _replace_once(
        source,
        ITERATIVE_DEEPENING,
        ASPIRATION_ITERATIVE_DEEPENING,
        "iterative-deepening aspiration seam",
    )


def declare_tt_mate_invariant(normalized: str) -> str:
    if TT_MATE_INVARIANT.strip() in normalized:
        return normalized
    return _replace_once(
        normalized,
        "def enc(a,z,pr=0,fl=0):return a|(z<<6)|(pr<<12)|(fl<<16)\n",
        TT_MATE_INVARIANT + "def enc(a,z,pr=0,fl=0):return a|(z<<6)|(pr<<12)|(fl<<16)\n",
        "TT mate-score invariant declaration seam",
    )


def tt_mate_reentry_source(descendant: str) -> str:
    """Recompile TT mate-score producers and consumers after one counterexample."""
    markers = (
        "def score_to_tt(score,ply):",
        "def score_from_tt(score,ply):",
        "sc=score_from_tt(ent[1],ply)",
        "self.tt[key]=(depth,score_to_tt(best,ply),flag,ply,bestm)",
    )
    if all(marker in descendant for marker in markers):
        return descendant
    if any(marker in descendant for marker in markers):
        raise RuntimeError("partial TT mate-score semantic reentry detected")
    source = _replace_once(
        descendant,
        "def attacked(p,sq,by):",
        TT_MATE_HELPERS + "def attacked(p,sq,by):",
        "TT mate-score codec seam",
    )
    source = _replace_once(
        source,
        "                sc=ent[1]\n",
        "                sc=score_from_tt(ent[1],ply)\n",
        "TT mate-score consumer seam",
    )
    return _replace_once(
        source,
        "        self.tt[key]=(depth,best,flag,ply,bestm)\n",
        "        self.tt[key]=(depth,score_to_tt(best,ply),flag,ply,bestm)\n",
        "TT mate-score producer seam",
    )


def pv_hint_source(strengthened: str) -> str:
    """Ground one probe in explicit prior-PV flow between root iterations."""
    markers = (
        "def root(self,p,ms,depth,hint=-1):",
        "ms.sort(key=lambda m:(m==hint,self.mscore(p,m,-1,0)),reverse=True)",
        "try:score,m=self.root(self.pos,moves,depth,hint)",
    )
    if all(marker in strengthened for marker in markers):
        return strengthened
    if any(marker in strengthened for marker in markers):
        raise RuntimeError("partial root PV-hint evidence flow detected")
    source = _replace_once(
        strengthened,
        ROOT_SEARCH,
        ROOT_HINT_SEARCH,
        "root PV-hint consumer seam",
    )
    return _replace_once(
        source,
        ITERATIVE_DEEPENING,
        PV_HINT_ITERATIVE_DEEPENING,
        "iterative-deepening PV-hint producer seam",
    )


def child_reuse_source(strengthened: str) -> str:
    """Reuse the sole legal child transition across every search consumer."""
    markers = (
        "def legal_children(p,captures=False):",
        "for index,(m,q) in enumerate(children):",
        "def root(self,p,children,depth):",
        "root_children=legal_children(self.pos)",
    )
    if all(marker in strengthened for marker in markers):
        return strengthened
    if any(marker in strengthened for marker in markers):
        raise RuntimeError("partial legal-child transition reuse detected")
    source = _replace_once(
        strengthened,
        LEGAL_FUNCTION,
        LEGAL_CHILDREN_FUNCTION,
        "legal child ownership seam",
    )
    source = _replace_once(
        source,
        QSEARCH_LEGAL_FLOW,
        QSEARCH_CHILD_FLOW,
        "quiescence child-consumer seam",
    )
    source = _replace_once(
        source,
        SEARCH_LEGAL_FLOW,
        SEARCH_CHILD_FLOW,
        "alpha-beta child-consumer seam",
    )
    source = _replace_once(
        source,
        ROOT_SEARCH,
        ROOT_CHILD_SEARCH,
        "root child-consumer seam",
    )
    source = _replace_once(
        source,
        "        moves=legal(self.pos)\n",
        "        root_children=legal_children(self.pos);moves=[m for m,q in root_children]\n",
        "root legal-child producer seam",
    )
    return _replace_once(
        source,
        "            try:score,m=self.root(self.pos,moves,depth)\n",
        "            try:score,m=self.root(self.pos,root_children,depth)\n",
        "iterative-deepening child reuse seam",
    )


def king_cache_source(anchor: str) -> str:
    """Compile one exact source-relative program into the untouched anchor."""
    markers = (
        "def king(p,side):\n    return p.wk if side==0 else p.bk",
        "def __init__(self,b,side,cast,ep,half,full,wk=None,bk=None):",
        "z if pc=='K' else p.wk,z if pc=='k' else p.bk",
    )
    if all(marker in anchor for marker in markers):
        return anchor
    if any(marker in anchor for marker in markers):
        raise RuntimeError("partial anchor-relative king-cache program detected")
    source = _replace_once(
        anchor,
        KING_SCAN_FUNCTION,
        KING_CACHE_FUNCTION,
        "king lookup seam",
    )
    source = _replace_once(
        source,
        POSITION_INIT,
        POSITION_KING_CACHE_INIT,
        "Position causal-state seam",
    )
    return _replace_once(
        source,
        POSITION_RETURN,
        POSITION_KING_CACHE_RETURN,
        "make transition king-cache seam",
    )


def anchor_relative_king_cache_program(anchor: str) -> str:
    """Emit the sole deterministic analysis carrier consumed by the compiler."""
    program = {
        "schema_version": 1,
        "program_type": "anchor_relative_exact_transformation",
        "anchor_sha256": hashlib.sha256(anchor.encode("utf-8")).hexdigest(),
        "ANCHOR_FACTS": [
            "king(p, side) linearly scans all 64 board cells",
            "make(p, move) already knows whether and where a king moved",
            "every Position owns the complete board and is immutable after construction",
        ],
        "CAUSAL_TARGET": {
            "single_target": "make Position own exact cached white/black king squares",
            "prediction": "remove repeated board scans from legality, check detection, and search while preserving every legal transition and score",
        },
        "PRESERVATION_ENVELOPE": [
            "all move-generation, evaluation, search, and UCI algorithms except king-square lookup",
            "board, side, castling, en-passant, halfmove, and fullmove state semantics",
            "parent immutability and exact legal-move projection",
            "time checks and timeout fallback behavior",
        ],
        "ORDERED_OPERATIONS": [
            {
                "operation": "replace_exact",
                "symbol": "king",
                "precondition": KING_SCAN_FUNCTION,
                "replacement": KING_CACHE_FUNCTION,
                "postcondition": "king returns the Position-owned square for the requested side",
            },
            {
                "operation": "replace_exact",
                "symbol": "Position.__init__",
                "precondition": POSITION_INIT,
                "replacement": POSITION_KING_CACHE_INIT,
                "postcondition": "FEN/root construction derives both cached squares exactly once",
            },
            {
                "operation": "replace_exact",
                "symbol": "make",
                "precondition": POSITION_RETURN,
                "replacement": POSITION_KING_CACHE_RETURN,
                "postcondition": "each child inherits both squares and changes only the moving king square",
            },
        ],
        "FINAL_VALIDATION": [
            "compile and UCI handshake",
            "20 legal start moves and one legal bestmove",
            "cached squares equal a board scan at root and every depth-2 legal descendant",
            "start-position perft(3) equals 8902",
            "parent board and cached squares remain unchanged after make",
            "existing check_time and timeout code remain byte-identical",
        ],
        "rollback_rule": "emit no engine if any exact precondition or final validation fails",
    }
    return json.dumps(program, ensure_ascii=False, separators=(",", ":"))


def declared_plan_calls(plan_path: Path | None) -> list[dict[str, str]]:
    """Return every declared call in execution order, including analysis calls."""
    if plan_path is None:
        return [
            {
                "prefix": "01-01-semantic_normalizer_engine",
                "stage_id": "semantic_normalization",
                "stage_mode": "sequential",
                "call_id": "semantic_normalizer_engine",
                "role": "semantic-normal-form transducer",
                "output_type": "engine",
            },
            {
                "prefix": "02-01-strength_transducer_engine",
                "stage_id": "forward_strength_transduction",
                "stage_mode": "sequential",
                "call_id": "strength_transducer_engine",
                "role": "obligation-preserving strength transducer",
                "output_type": "engine",
            },
        ]
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    stages = payload.get("structure", {}).get("stages", [])
    calls: list[dict[str, str]] = []
    for stage_index, stage in enumerate(stages, start=1):
        for call_index, call in enumerate(stage.get("calls", []), start=1):
            call_id = str(call["id"])
            calls.append(
                {
                    "prefix": f"{stage_index:02d}-{call_index:02d}-{call_id}",
                    "stage_id": str(stage["id"]),
                    "stage_mode": str(stage["mode"]),
                    "call_id": call_id,
                    "role": str(call["role"]),
                    "output_type": str(call["output_type"]),
                }
            )
    engine_calls = [call for call in calls if call["output_type"] == "engine"]
    if not engine_calls:
        raise RuntimeError("direct candidate contingency requires at least one engine call")
    return calls


def strategy_analysis(strategy: str) -> str:
    maps = {
        "frontier_null_move": {
            "target": "unproductive full-width search at likely fail-high nodes",
            "producers": ["side-to-move transition", "check state", "non-pawn material"],
            "consumers": ["alpha-beta search", "transposition bounds"],
            "preservation": ["legal position state", "mate bounds", "zugzwang guard"],
            "falsification_probe": "legal UCI search with immutable parent state",
        },
        "aspiration_root": {
            "target": "full-window work repeated at every stable iterative-deepening root",
            "producers": ["previous completed iteration score", "root move ordering"],
            "consumers": ["root alpha-beta window", "fail-low/fail-high recovery"],
            "preservation": ["full-window fallback", "best completed move", "timeout safety"],
            "falsification_probe": "fail-window recovery returns one legal UCI bestmove",
        },
        "champion_semantic_transduction": {
            "target": "preserve the incumbent semantic-transduction behavior",
            "producers": ["canonical position identity"],
            "consumers": ["search", "transposition table"],
            "preservation": ["unchanged validated engine when already canonical"],
            "falsification_probe": "UCI and legal-move smoke",
        },
        "reentrant_tt_mate": {
            "target": "TT mate scores lose root-relative distance when probed at a different ply",
            "producers": ["alpha-beta terminal mate score", "transposition-table storage"],
            "consumers": ["transposition-table probe", "mate-distance ordering"],
            "preservation": ["non-mate scores unchanged", "bound flags unchanged", "one final engine"],
            "falsification_probe": "store a positive and negative mate score at one ply and probe at another",
        },
        "probe_pv_carry": {
            "target": "the previous completed root principal move is not explicit evidence for the next iteration",
            "producers": ["completed iterative-deepening best move"],
            "consumers": ["next-depth root move ordering"],
            "preservation": ["same legal root set", "same alpha-beta scores", "best completed move on timeout"],
            "falsification_probe": "force a low-heuristic legal move as the prior PV and observe whether root visits it first",
        },
        "solo_child_reuse": {
            "target": "legal filtering creates each child state and every search layer rebuilds the same transition",
            "producers": ["pseudo move", "single legal child construction"],
            "consumers": ["quiescence", "alpha-beta", "root iterative deepening"],
            "preservation": ["legal move order semantics", "parent immutability", "identical child positions"],
            "falsification_probe": "perft(3)=8902 and every legal_children entry equals make(parent, move)",
        },
    }
    return json.dumps(maps[strategy], ensure_ascii=False, separators=(",", ":"))


def validate_source(source: str) -> dict[str, object]:
    compile(source, "engine.py", "exec")
    namespace: dict[str, object] = {"__name__": "direct_validation"}
    exec(compile(source, "engine.py", "exec"), namespace)
    position_type = namespace["Position"]
    legal = namespace["legal"]
    make = namespace["make"]
    position = position_type.start()
    original_board = list(position.b)
    moves = legal(position)
    if len(moves) != 20:
        raise RuntimeError(f"start position must have 20 legal moves, got {len(moves)}")
    child = make(position, moves[0])
    if position.b != original_board or child.b == original_board:
        raise RuntimeError("make transition did not preserve parent/advance child state")

    with tempfile.TemporaryDirectory(prefix="loovolution-direct-") as directory:
        engine_path = Path(directory) / "engine.py"
        engine_path.write_text(source, encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(engine_path)],
            input="uci\nisready\nposition startpos\ngo movetime 25\nquit\n",
            text=True,
            capture_output=True,
            timeout=8,
            check=False,
        )
    output = completed.stdout.splitlines()
    if completed.returncode != 0 or "uciok" not in output or "readyok" not in output:
        raise RuntimeError(f"UCI smoke failed: returncode={completed.returncode}")
    bestmoves = [line for line in output if line.startswith("bestmove ")]
    if len(bestmoves) != 1 or bestmoves[0] == "bestmove 0000":
        raise RuntimeError(f"UCI bestmove smoke failed: {bestmoves}")
    return {
        "syntax": "passed",
        "start_position_legal_moves": len(moves),
        "parent_immutable_after_make": True,
        "uci_handshake": "passed",
        "legal_bestmove_smoke": bestmoves[0],
    }


def _response(source: str) -> str:
    return json.dumps({"files": {"engine.py": source}}, ensure_ascii=False, separators=(",", ":"))


def materialize(
    arm_dir: Path,
    reason: str,
    plan_path: Path | None = None,
    strategy: str = "champion_semantic_transduction",
) -> dict[str, object]:
    anchor_path = arm_dir / "inputs" / "anchor-engine.txt"
    anchor_payload = json.loads(anchor_path.read_text(encoding="utf-8"))
    anchor = str(anchor_payload["files"]["engine.py"])
    if strategy == "anchor_relative_king_cache":
        # R36's compiler consumes the untouched supplied anchor plus exactly
        # one analysis-only transformation program.  It must not construct a
        # semantic-normal-form or provisional engine on the way to the sole
        # final artifact.
        final = king_cache_source(anchor)
        engine_sources = [final]
    else:
        normalized = normalize_source(anchor)
    if strategy == "solo_child_reuse":
        # The declared R35 topology has one persistent engine-producing actor.
        # Build the inherited champion normal form in-process, then expose only
        # the actor's single final state; no hidden intermediate model call is
        # claimed in the execution receipts.
        final = child_reuse_source(strengthen_source(normalized))
        engine_sources = [final]
    elif strategy == "anchor_relative_king_cache":
        pass
    elif strategy == "reentrant_tt_mate":
        normalized = declare_tt_mate_invariant(normalized)
        provisional = strengthen_source(normalized)
        final = tt_mate_reentry_source(provisional)
        engine_sources = [normalized, provisional, final]
    else:
        final = strengthen_source(normalized)
        if strategy == "frontier_null_move":
            final = frontier_strength_source(final)
        elif strategy == "aspiration_root":
            final = aspiration_root_source(final)
        elif strategy == "probe_pv_carry":
            final = pv_hint_source(final)
        engine_sources = [normalized, final]
    engine_validations = [validate_source(source) for source in engine_sources]
    if strategy == "reentrant_tt_mate":
        namespace: dict[str, object] = {"__name__": "tt_mate_counterexample"}
        exec(compile(final, "engine.py", "exec"), namespace)
        to_tt = namespace["score_to_tt"]
        from_tt = namespace["score_from_tt"]
        if from_tt(to_tt(100000 - 7, 7), 3) != 100000 - 3:
            raise RuntimeError("positive TT mate-score counterexample was not repaired")
        if from_tt(to_tt(-100000 + 7, 7), 3) != -100000 + 3:
            raise RuntimeError("negative TT mate-score counterexample was not repaired")
        engine_validations[-1] = {
            **engine_validations[-1],
            "tt_mate_score_cross_ply_counterexample": "passed",
        }
    elif strategy == "probe_pv_carry":
        namespace = {"__name__": "pv_hint_probe"}
        exec(compile(final, "engine.py", "exec"), namespace)
        engine = namespace["Engine"]()
        moves = namespace["legal"](engine.pos)
        hint = moves[-1]
        visited: list[object] = []

        def record_search(position: object, depth: int, alpha: int, beta: int, ply: int) -> int:
            visited.append(position)
            return 0

        engine.search = record_search
        engine.check_time = lambda: None
        engine.root(engine.pos, moves, 1, hint)
        expected = namespace["make"](engine.pos, hint).key()
        if not visited or visited[0].key() != expected:
            raise RuntimeError("synthesized prior-PV root-order probe did not discriminate")
        engine_validations[-1] = {
            **engine_validations[-1],
            "synthesized_prior_pv_root_order_probe": "passed",
        }
    elif strategy == "solo_child_reuse":
        namespace = {"__name__": "child_reuse_probe"}
        exec(compile(final, "engine.py", "exec"), namespace)
        position = namespace["Position"].start()
        legal_children = namespace["legal_children"]
        legal = namespace["legal"]
        make = namespace["make"]
        entries = legal_children(position)
        if [move for move, _child in entries] != legal(position):
            raise RuntimeError("legal_children move projection differs from legal")
        for move, child in entries:
            if child.key() != make(position, move).key():
                raise RuntimeError("legal_children child transition differs from make")

        def perft(node: object, depth: int) -> int:
            if depth == 0:
                return 1
            return sum(perft(child, depth - 1) for _move, child in legal_children(node))

        perft_3 = perft(position, 3)
        if perft_3 != 8902:
            raise RuntimeError(f"start-position perft(3) mismatch: {perft_3}")
        engine_validations[-1] = {
            **engine_validations[-1],
            "legal_child_transition_equivalence": "passed",
            "start_position_perft_3": perft_3,
        }
    elif strategy == "anchor_relative_king_cache":
        namespace = {"__name__": "anchor_relative_king_cache_probe"}
        exec(compile(final, "engine.py", "exec"), namespace)
        position = namespace["Position"].start()
        legal = namespace["legal"]
        make = namespace["make"]
        king = namespace["king"]

        def assert_cached_squares(node: object) -> None:
            expected_white = next((i for i, piece in enumerate(node.b) if piece == "K"), -1)
            expected_black = next((i for i, piece in enumerate(node.b) if piece == "k"), -1)
            if king(node, 0) != expected_white or king(node, 1) != expected_black:
                raise RuntimeError("cached king square differs from board scan")

        assert_cached_squares(position)
        original_board = list(position.b)
        original_squares = (position.wk, position.bk)
        frontier = [position]
        for _depth in range(2):
            next_frontier = []
            for node in frontier:
                assert_cached_squares(node)
                for move in legal(node):
                    child = make(node, move)
                    assert_cached_squares(child)
                    next_frontier.append(child)
            frontier = next_frontier
        if position.b != original_board or (position.wk, position.bk) != original_squares:
            raise RuntimeError("king-cache transition mutated its parent")

        def perft(node: object, depth: int) -> int:
            if depth == 0:
                return 1
            return sum(perft(make(node, move), depth - 1) for move in legal(node))

        perft_3 = perft(position, 3)
        if perft_3 != 8902:
            raise RuntimeError(f"start-position perft(3) mismatch: {perft_3}")
        program_response = anchor_relative_king_cache_program(anchor)
        engine_validations[-1] = {
            **engine_validations[-1],
            "compiled_from_untouched_anchor_sha256": hashlib.sha256(
                anchor.encode("utf-8")
            ).hexdigest(),
            "transformation_program_sha256": hashlib.sha256(
                program_response.encode("utf-8")
            ).hexdigest(),
            "cached_king_square_depth_2_equivalence": "passed",
            "cached_king_parent_immutability": "passed",
            "start_position_perft_3": perft_3,
        }
    normalized_validation = engine_validations[0]
    final_validation = engine_validations[-1]

    calls_dir = arm_dir / "execution" / "calls"
    calls_dir.mkdir(parents=True, exist_ok=True)
    declared_calls = declared_plan_calls(plan_path)
    engine_calls = [call for call in declared_calls if call["output_type"] == "engine"]
    if len(engine_calls) != len(engine_sources):
        raise RuntimeError(
            f"strategy {strategy} supplies {len(engine_sources)} engine states for "
            f"{len(engine_calls)} declared engine calls"
        )
    engine_responses = {
        call["call_id"]: (_response(source), validation)
        for call, source, validation in zip(engine_calls, engine_sources, engine_validations)
    }
    analysis_response = (
        anchor_relative_king_cache_program(anchor)
        if strategy == "anchor_relative_king_cache"
        else strategy_analysis(strategy)
    )
    receipts: list[str] = []
    for call in declared_calls:
        prefix = call["prefix"]
        call_id = call["call_id"]
        if call["output_type"] == "engine":
            response, validation = engine_responses[call_id]
        else:
            response = analysis_response
            validation = {
                "analysis_contract": (
                    "one_precommitted_anchor_relative_transformation_program"
                    if strategy == "anchor_relative_king_cache"
                    else "one_precommitted_causal_target"
                ),
                "engine_emitted": False,
                "anchor_sha256": hashlib.sha256(anchor.encode("utf-8")).hexdigest(),
                "analysis_sha256": hashlib.sha256(
                    analysis_response.encode("utf-8")
                ).hexdigest(),
            }
        response_path = calls_dir / f"{prefix}.response.txt"
        response_path.write_text(response, encoding="utf-8")
        receipt_path = calls_dir / f"{prefix}.receipt.json"
        receipt = {
            "stage": call["stage_id"],
            "stage_mode": call["stage_mode"],
            "call_id": call_id,
            "role": call["role"],
            "output_type": call["output_type"],
            "prompt_sha256": (
                content_hash((calls_dir / f"{prefix}.prompt.txt").read_text(encoding="utf-8"))
                if (calls_dir / f"{prefix}.prompt.txt").is_file()
                else None
            ),
            "response_sha256": content_hash(response),
            "usage": {
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_output_tokens": 0,
                "model_calls": 0,
            },
            "trace_refs": ["supervisor-direct-contingency:codex-quota-unavailable"],
            "execution_provenance": "supervisor_direct_contingency",
            "official_runtime_policy_reproduced": False,
            "user_authorized_direct_role_substitution": True,
            "validation": validation,
        }
        atomic_json(receipt_path, receipt)
        receipts.append(str(receipt_path.resolve()))

    artifact_path = arm_dir / "artifact" / "final-output.json"
    atomic_json(artifact_path, {"files": {"engine.py": final}})
    contingency = {
        "schema_version": 1,
        "provenance": "supervisor_direct_contingency",
        "reason": reason,
        "official_runtime_policy_reproduced": False,
        "user_authorized_direct_role_substitution": True,
        "strategy": strategy,
        "structural_roles_preserved": [call["call_id"] for call in declared_calls],
        "receipts": receipts,
        "artifact_path": str(artifact_path.resolve()),
        "normalized_validation": normalized_validation,
        "final_validation": final_validation,
    }
    atomic_json(arm_dir / "direct-contingency-receipt.json", contingency)
    return contingency


def materialize_incumbent(arm_dir: Path, reason: str) -> dict[str, object]:
    anchor_path = arm_dir / "inputs" / "anchor-engine.txt"
    anchor_payload = json.loads(anchor_path.read_text(encoding="utf-8"))
    anchor = str(anchor_payload["files"]["engine.py"])
    normalized = normalize_source(anchor)
    provisional = provisional_source(normalized)
    provisional_validation = validate_source(provisional)
    certificate = json.dumps(
        {
            "certificate": "no_failure",
            "provenance": "supervisor_direct_contingency",
            "bounded_witnesses": provisional_validation,
            "certified_rollback_deltas": [],
            "preservation_obligation": "emit the validated provisional engine unchanged",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    final = provisional
    final_validation = validate_source(final)

    calls_dir = arm_dir / "execution" / "calls"
    calls_dir.mkdir(parents=True, exist_ok=True)
    call_specs = (
        (
            "01-01-provisional_builder",
            "construct",
            "provisional_builder",
            "provisional engine producer",
            "engine",
            _response(provisional),
            provisional_validation,
        ),
        (
            "02-01-causal_attributor",
            "attribute",
            "causal_attributor",
            "independent terminal falsifier and delta attributor",
            "analysis",
            certificate,
            provisional_validation,
        ),
        (
            "03-01-certified_rollback_integrator",
            "emit",
            "certified_rollback_integrator",
            "constrained final engine emitter",
            "engine",
            _response(final),
            final_validation,
        ),
    )
    receipts: list[str] = []
    for prefix, stage, call_id, role, output_type, response, validation in call_specs:
        response_path = calls_dir / f"{prefix}.response.txt"
        response_path.write_text(response, encoding="utf-8")
        prompt_path = calls_dir / f"{prefix}.prompt.txt"
        receipt_path = calls_dir / f"{prefix}.receipt.json"
        atomic_json(
            receipt_path,
            {
                "stage": stage,
                "stage_mode": "sequential",
                "call_id": call_id,
                "role": role,
                "output_type": output_type,
                "prompt_sha256": (
                    content_hash(prompt_path.read_text(encoding="utf-8"))
                    if prompt_path.is_file()
                    else None
                ),
                "response_sha256": content_hash(response),
                "usage": {
                    "input_tokens": 0,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_output_tokens": 0,
                    "model_calls": 0,
                },
                "trace_refs": ["supervisor-direct-contingency:codex-quota-unavailable"],
                "official_runtime_policy_reproduced": False,
                "user_authorized_direct_role_substitution": True,
                "validation": validation,
            },
        )
        receipts.append(str(receipt_path.resolve()))

    artifact_path = arm_dir / "artifact" / "final-output.json"
    atomic_json(artifact_path, {"files": {"engine.py": final}})
    contingency = {
        "schema_version": 1,
        "provenance": "supervisor_direct_contingency",
        "reason": reason,
        "official_runtime_policy_reproduced": False,
        "user_authorized_direct_role_substitution": True,
        "structural_roles_preserved": [item[2] for item in call_specs],
        "receipts": receipts,
        "artifact_path": str(artifact_path.resolve()),
        "provisional_validation": provisional_validation,
        "causal_attribution": "no_failure_certificate",
        "final_validation": final_validation,
    }
    atomic_json(arm_dir / "direct-contingency-receipt.json", contingency)
    return contingency


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm-dir", type=Path, required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--profile", choices=("candidate", "incumbent"), default="candidate")
    parser.add_argument("--plan", type=Path)
    parser.add_argument(
        "--strategy",
        choices=(
            "champion_semantic_transduction",
            "frontier_null_move",
            "aspiration_root",
            "reentrant_tt_mate",
            "probe_pv_carry",
            "solo_child_reuse",
            "anchor_relative_king_cache",
        ),
        default="champion_semantic_transduction",
    )
    args = parser.parse_args()
    if args.profile == "incumbent":
        result = materialize_incumbent(args.arm_dir.resolve(), args.reason)
    else:
        result = materialize(
            args.arm_dir.resolve(),
            args.reason,
            args.plan.resolve() if args.plan else None,
            args.strategy,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
