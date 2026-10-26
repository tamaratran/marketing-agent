"""The cycle writes its outcome onto the runs row the site created, so the Runs page can show
stage status and done/failed instead of only a session link."""

import json

from marketing_agent.orchestrator import DailyReport, record_stage
from marketing_agent.store import Store


def test_report_records_outcome_on_open_run(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    rid = store.insert(
        "runs",
        {
            "created_at": 1,
            "session_id": "abc",
            "url": "u",
            "niche": "fitness",
            "product": "p",
            "note": "",
        },
    )
    rep = DailyReport("fitness", "p")
    rep.ok("measure", 1.0)
    rep.fail("render", RuntimeError("needs a top-up at fal.ai/dashboard/billing: locked"))
    assert rep.record(store) == rid
    row = store.rows("SELECT * FROM runs WHERE id=?", (rid,))[0]
    assert row["status"] == "failed" and row["finished_at"]
    assert [s["stage"] for s in json.loads(row["stages"])] == ["measure", "render"]


def test_cli_started_cycle_gets_its_own_row(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    rep = DailyReport("fitness", "p")
    rep.ok("measure", 1.0)
    rid = rep.record(store)
    row = store.rows("SELECT * FROM runs WHERE id=?", (rid,))[0]
    assert row["status"] == "ok" and row["session_id"] == ""


def test_rerun_outcome_replaces_the_first_attempt(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    store.insert(
        "runs",
        {
            "created_at": 1,
            "session_id": "abc",
            "url": "u",
            "niche": "fitness",
            "product": "p",
            "note": "",
        },
    )
    rep = DailyReport("fitness", "p")
    rep.ok("measure", 1.0)
    rep.fail("render", RuntimeError("probe broke"))
    rid = rep.record(store)
    assert record_stage(store, "fitness", "render", "ok", "rerun after fix: s125") == rid
    row = store.rows("SELECT * FROM runs WHERE id=?", (rid,))[0]
    stages = {s["stage"]: s for s in json.loads(row["stages"])}
    assert (
        stages["render"]["status"] == "ok" and stages["render"]["note"] == "rerun after fix: s125"
    )
    assert row["status"] == "ok"
    assert record_stage(store, "other-niche", "render", "ok") is None
