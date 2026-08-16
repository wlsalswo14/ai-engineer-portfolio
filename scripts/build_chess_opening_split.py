from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path

import chess


LETTERS = "ABCDE"
DECADES = tuple(f"{letter}{number:02d}" for letter in LETTERS for number in range(0, 100, 10))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def parse_line(eco: str, name: str, pgn: str, source_file: str) -> dict[str, object] | None:
    board = chess.Board()
    moves: list[str] = []
    try:
        for token in pgn.split():
            if token.endswith(".") or token.replace(".", "").isdigit():
                continue
            move = board.parse_san(token)
            moves.append(move.uci())
            board.push(move)
    except ValueError:
        return None
    if not board.is_valid() or board.is_game_over(claim_draw=True):
        return None
    return {
        "source_eco": eco,
        "name": name,
        "source_file": source_file,
        "pgn": pgn,
        "uci": moves,
        "plies": len(moves),
        "fen": board.fen(),
    }


def decile(eco: str) -> str:
    return f"{eco[0]}{(int(eco[1:]) // 10) * 10:02d}"


def stable_rank(commit: str, target: str, row: dict[str, object]) -> str:
    value = f"{commit}\0{target}\0{row['source_eco']}\0{row['name']}\0{row['pgn']}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_hidden(
    *, public_source: Path, tsv_dir: Path, commit: str, output: Path
) -> dict[str, object]:
    public = json.loads(public_source.read_text(encoding="utf-8"))
    public_rows = {str(item["eco"]): item for item in public["openings"]}
    if set(public_rows) != set(DECADES):
        raise ValueError("public opening source does not cover exactly the 50 ECO deciles")
    public_fens = {str(item["fen"]) for item in public_rows.values()}

    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    tsv_hashes: dict[str, str] = {}
    for letter in LETTERS.lower():
        path = tsv_dir / f"{letter}.tsv"
        tsv_hashes[path.name] = sha256_file(path)
        with path.open(encoding="utf-8", newline="") as handle:
            for raw in csv.DictReader(handle, delimiter="\t"):
                parsed = parse_line(raw["eco"], raw["name"], raw["pgn"], path.name)
                if parsed is not None:
                    grouped[decile(raw["eco"])].append(parsed)

    chosen: list[dict[str, object]] = []
    hidden_fens: set[str] = set()
    for target in DECADES:
        public_row = public_rows[target]
        candidates = [
            row
            for row in grouped[target]
            if row["fen"] not in public_fens and row["fen"] not in hidden_fens
        ]
        candidates.sort(
            key=lambda row: (
                abs(int(row["plies"]) - int(public_row["plies"])),
                stable_rank(commit, target, row),
            )
        )
        if not candidates:
            raise ValueError(f"no disjoint hidden opening is available for {target}")
        selected = candidates[0]
        hidden_fens.add(str(selected["fen"]))
        chosen.append({"id": f"hidden-b-{target.lower()}", "eco": target, **selected})

    if public_fens & hidden_fens or len(hidden_fens) != 50:
        raise ValueError("public and hidden opening FENs are not strictly disjoint")
    result = {
        "schema_version": 1,
        "id": "primus-chess-hidden-b-eco-deciles-50-v1",
        "source": {
            "repository": "https://github.com/lichess-org/chess-openings",
            "commit": commit,
            "license": "CC0-1.0",
            "tsv_sha256": tsv_hashes,
        },
        "selection": {
            "method": "one alternate per ECO decile; closest public ply depth, SHA-256 tie-break",
            "public_source_sha256": sha256_file(public_source),
            "strict_fen_disjointness": True,
        },
        "openings": chosen,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-source", type=Path, required=True)
    parser.add_argument("--tsv-dir", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    public_output = args.output_dir / "chess-development-a.json"
    shutil.copyfile(args.public_source, public_output)
    hidden_output = args.output_dir / "chess-certification-b.json"
    hidden = build_hidden(
        public_source=public_output,
        tsv_dir=args.tsv_dir,
        commit=args.commit,
        output=hidden_output,
    )
    print(json.dumps({
        "public": str(public_output.resolve()),
        "public_sha256": sha256_file(public_output),
        "hidden": str(hidden_output.resolve()),
        "hidden_sha256": sha256_file(hidden_output),
        "fen_overlap": len({item["fen"] for item in hidden["openings"]} & {
            item["fen"] for item in json.loads(public_output.read_text(encoding="utf-8"))["openings"]
        }),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
