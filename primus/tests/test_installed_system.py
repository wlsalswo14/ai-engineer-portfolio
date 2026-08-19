from pathlib import Path

from primus.doctor import doctor
from primus.config import load_system
from primus.cost import pipeline_cost
from primus.jsonutil import read_json


ROOT = Path(__file__).resolve().parents[1]


def test_installed_system_passes_doctor() -> None:
    checks = doctor(ROOT)
    assert "legacy-quarantined" in checks


def test_every_configured_domain_has_an_active_pointer() -> None:
    for domain in load_system(ROOT).domains:
        pointer = read_json(ROOT / "registry" / "domains" / domain / "active.json")
        assert pointer["domain"] == domain


def test_r81_and_ecr_are_legacy_only() -> None:
    manifests = list((ROOT / "registry" / "legacy" / "r81").rglob("manifest.json"))
    manifests += list((ROOT / "registry" / "legacy" / "ecr").rglob("manifest.json"))
    assert manifests
    assert all(read_json(path)["never_active"] is True for path in manifests)


def test_staged_chess_cost_is_24_or_48() -> None:
    value = pipeline_cost(ROOT, "chess", candidate_calls=4)
    assert value["screening_reject"]["executor_calls"] == 24
    assert "attribution_reject" not in value
    assert value["full_certification"]["executor_calls"] == 48
    assert value["full_certification"]["chess_games"] == 1200


def test_staged_cache_cost_includes_the_public_portfolio_probe() -> None:
    value = pipeline_cost(ROOT, "cache", candidate_calls=2)
    assert value["portfolio_probe"]["executor_calls"] == 4
    assert value["screening_reject"]["executor_calls"] == 16
    assert "attribution_reject" not in value
    assert value["full_certification"]["executor_calls"] == 28


def test_chess_public_and_certification_openings_are_disjoint() -> None:
    public_taskset = read_json(ROOT / "config" / "tasksets" / "chess-development.json")
    hidden_taskset = read_json(ROOT / "config" / "tasksets" / "chess-certification.json")
    public = read_json(Path(public_taskset["cases"][0]["metadata"]["openings_path"]))
    hidden = read_json(Path(hidden_taskset["cases"][0]["metadata"]["openings_path"]))
    public_fens = {item["fen"] for item in public["openings"]}
    hidden_fens = {item["fen"] for item in hidden["openings"]}
    assert len(public_fens) == len(hidden_fens) == 50
    assert public_fens.isdisjoint(hidden_fens)
    assert public_taskset["cases"][0]["metadata"]["openings_sha256"] != hidden_taskset["cases"][0]["metadata"]["openings_sha256"]
