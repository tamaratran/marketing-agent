"""`mkt stage` runs end to end against a db with one recorded run."""

import json
import time

from click.testing import CliRunner

from marketing_agent import cli as cli_mod
from marketing_agent.store import Store


def test_stage_updates_newest_run(tmp_path, monkeypatch):
    db = tmp_path / "t.sqlite"
    monkeypatch.setenv("MKT_DB", str(db))
    store = Store(db)
    from marketing_agent import campaign

    niche = campaign.load().niche.name
    with store.conn() as c:
        for col, typ in (("status", "TEXT"), ("stages", "TEXT"), ("finished_at", "INTEGER")):
            c.execute(f"ALTER TABLE runs ADD COLUMN {col} {typ}")
    rid = store.insert(
        "runs",
        {
            "created_at": int(time.time()),
            "session_id": "s",
            "url": "u",
            "niche": niche,
            "product": "p",
            "note": "",
            "status": "failed",
            "finished_at": 1,
            "stages": json.dumps(
                [{"stage": "render", "status": "failed", "seconds": 0, "note": "old"}]
            ),
        },
    )
    res = CliRunner().invoke(cli_mod.cli, ["stage", "render", "ok", "rerun: s125"])
    assert res.exit_code == 0, res.output
    row = store.rows("SELECT status, stages FROM runs WHERE id=?", (rid,))[0]
    assert row["status"] == "ok"
    assert json.loads(row["stages"])[0]["note"] == "rerun: s125"
