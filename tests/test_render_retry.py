"""render-latest retries a provider error once, then skips that script; record_stage hits the newest run."""

import json
import time

from marketing_agent.cli import _transient
from marketing_agent.orchestrator import record_stage
from marketing_agent.store import Store


def test_transient_errors():
    assert _transient(RuntimeError("500 Downstream service error (downstream_service_error)"))
    assert _transient(RuntimeError("request timed out"))
    assert not _transient(RuntimeError("User is locked. Reason: Exhausted balance"))
    assert not _transient(RuntimeError("422 Field required"))


def test_record_stage_targets_newest_run_even_without_stages(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    with store.conn() as c:
        for col, typ in (("status", "TEXT"), ("stages", "TEXT"), ("finished_at", "INTEGER")):
            c.execute(f"ALTER TABLE runs ADD COLUMN {col} {typ}")
    old = store.insert(
        "runs",
        {
            "created_at": 1,
            "session_id": "a",
            "url": "u",
            "niche": "n",
            "product": "p",
            "note": "",
            "status": "ok",
            "finished_at": 2,
            "stages": json.dumps([{"stage": "render", "status": "ok", "seconds": 1, "note": ""}]),
        },
    )
    new = store.insert(
        "runs",
        {
            "created_at": int(time.time()),
            "session_id": "b",
            "url": "u",
            "niche": "n",
            "product": "p",
            "note": "clips only",
        },
    )
    assert record_stage(store, "n", "render", "failed", "fal 500") == new
    rows = {r["id"]: r for r in store.rows("SELECT id, status, stages FROM runs")}
    assert rows[old]["status"] == "ok" and json.loads(rows[old]["stages"])[0]["status"] == "ok"
    assert (
        rows[new]["status"] == "failed" and json.loads(rows[new]["stages"])[0]["note"] == "fal 500"
    )


def test_record_stage_skips_post_request_rows(tmp_path):
    """A Post press writes a `post s<id>` run row; a cycle's stage must land on the cycle, not it."""
    store = Store(tmp_path / "db.sqlite")
    with store.conn() as c:
        for col, typ in (("status", "TEXT"), ("stages", "TEXT"), ("finished_at", "INTEGER")):
            c.execute(f"ALTER TABLE runs ADD COLUMN {col} {typ}")
    base = {"created_at": 1, "session_id": "s", "url": "u", "niche": "n", "product": "P"}
    cycle = store.insert("runs", {**base, "note": "clips only: 5 at 720p"})
    store.insert("runs", {**base, "note": "post s125 from @us"})
    assert record_stage(store, "n", "render", "ok", "rendered 5") == cycle
