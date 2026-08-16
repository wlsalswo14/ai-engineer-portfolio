from __future__ import annotations

import json
from pathlib import Path

from loop_evolution.campaign import RoundCampaign
from loop_evolution.cli import _parser


class _FakeStore:
    def __init__(self, round_index: int) -> None:
        self.state = {"round_index": round_index}

    def migrate_to_matched_pairs(self) -> dict[str, int]:
        return dict(self.state)


class _FakePipeline:
    def __init__(
        self,
        workspace: Path,
        *,
        round_index: int,
        failures_before_success: int = 0,
    ) -> None:
        self.workspace = workspace
        self.config = {"display_round_offset": 19}
        self.store = _FakeStore(round_index)
        self.failures_before_success = failures_before_success
        self.calls = 0
        self.active_calls = 0
        self.maximum_active_calls = 0

    def run_round(self) -> dict[str, int]:
        self.calls += 1
        self.active_calls += 1
        self.maximum_active_calls = max(self.maximum_active_calls, self.active_calls)
        try:
            if self.failures_before_success:
                self.failures_before_success -= 1
                raise RuntimeError("temporary quota exhaustion")
            self.store.state["round_index"] += 1
            return {"round": self.store.state["round_index"]}
        finally:
            self.active_calls -= 1


def test_campaign_runs_sequentially_to_display_round_and_checkpoints(tmp_path: Path) -> None:
    pipeline = _FakePipeline(tmp_path, round_index=10)
    emitted: list[dict[str, object]] = []
    campaign = RoundCampaign(
        pipeline,
        target_display_round=31,
        retry_delay_seconds=0,
        sleep=lambda _: None,
        emit=emitted.append,
    )

    result = campaign.run()

    assert result["status"] == "completed"
    assert result["internal_round"] == 12
    assert result["display_round"] == 31
    assert pipeline.calls == 2
    assert pipeline.maximum_active_calls == 1
    control = json.loads((tmp_path / "campaign-control.json").read_text(encoding="utf-8"))
    assert control["status"] == "completed"
    assert control["target_display_round"] == 31
    events = [
        json.loads(line)
        for line in (tmp_path / "campaign-events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["event"] for event in events].count("round_completed") == 2
    assert emitted[-1]["event"] == "campaign_completed"


def test_campaign_retries_transient_failure_without_marking_blocked(tmp_path: Path) -> None:
    pipeline = _FakePipeline(tmp_path, round_index=10, failures_before_success=1)
    delays: list[float] = []
    campaign = RoundCampaign(
        pipeline,
        target_display_round=30,
        retry_delay_seconds=7,
        sleep=delays.append,
        emit=lambda _: None,
    )

    result = campaign.run()

    assert result["status"] == "completed"
    assert pipeline.calls == 2
    assert delays == [7]
    events = [
        json.loads(line)
        for line in (tmp_path / "campaign-events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    error = next(event for event in events if event["event"] == "round_failed_will_retry")
    assert error["error_type"] == "RuntimeError"
    assert "quota" in error["error"]
    assert all(event.get("status") != "blocked" for event in events)


def test_campaign_rejects_target_below_current_display_round(tmp_path: Path) -> None:
    pipeline = _FakePipeline(tmp_path, round_index=10)
    campaign = RoundCampaign(
        pipeline,
        target_display_round=28,
        retry_delay_seconds=0,
        sleep=lambda _: None,
        emit=lambda _: None,
    )

    try:
        campaign.run()
    except ValueError as exc:
        assert "behind current display round" in str(exc)
    else:
        raise AssertionError("campaign accepted a target behind the current round")

    assert pipeline.calls == 0


def test_cli_accepts_persistent_campaign_target() -> None:
    args = _parser().parse_args(
        ["run-until", "--target-display-round", "1000", "--retry-delay-seconds", "11"]
    )

    assert args.command == "run-until"
    assert args.target_display_round == 1000
    assert args.retry_delay_seconds == 11
