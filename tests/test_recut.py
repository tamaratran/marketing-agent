"""`mkt recut` re-captions an existing render at no generation cost: new hook and lines are saved
on the script, a new render row points at the re-assembled files, and nothing is paid to fal."""

import json
import time
from pathlib import Path

from click.testing import CliRunner

from marketing_agent import cli as cli_mod
from marketing_agent.store import Store


def _world(tmp_path, monkeypatch):
    monkeypatch.setenv("MKT_DB", str(tmp_path / "db.sqlite"))
    monkeypatch.setattr(cli_mod.settings, "data_dir", tmp_path)
    store = Store(tmp_path / "db.sqlite")
    store.migrate()
    now = int(time.time())
    payload = {
        "hook": "POV: cardio finally got fun",
        "captions": ["old line"],
        "hook_on_screen": True,
        "video_prompt": "a person plays the game",
    }
    sid = store.insert(
        "scripts",
        {
            "concept_id": 1,
            "product": "app",
            "created_at": now,
            "hook": payload["hook"],
            "body": "",
            "demo_score": 5,
            "payload": json.dumps(payload),
        },
    )
    raw = tmp_path / "s_raw.mp4"
    raw.write_bytes(b"raw moov")
    rid = store.insert(
        "renders",
        {
            "script_id": sid,
            "created_at": now,
            "model": "seedance",
            "prompt": "p",
            "raw_path": str(raw),
            "final_path": str(tmp_path / "old.mp4"),
            "cost_usd": 5.0,
            "payload": json.dumps({"input": {"resolution": "720p"}}),
        },
    )
    return store, sid, rid, raw


def test_recut_reuses_the_raw_clip_and_costs_nothing(tmp_path, monkeypatch):
    store, sid, rid, raw = _world(tmp_path, monkeypatch)
    assembled = []

    def fake_assemble(clips, out, captions=None, sound=None):
        assembled.append((list(clips), Path(out), captions, sound))
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"cut moov")
        return Path(out)

    monkeypatch.setattr("marketing_agent.video.edit.assemble", fake_assemble)
    monkeypatch.setattr("marketing_agent.video.edit.probe_duration", lambda p: 12.0)
    monkeypatch.setattr("marketing_agent.video.edit.probe", lambda p: {"duration_s": 12.0})

    res = CliRunner().invoke(
        cli_mod.cli,
        [
            "recut",
            str(sid),
            "--hook",
            "How many burned 300 calories just now?",
            "--caption",
            "new line",
        ],
    )
    assert res.exit_code == 0, res.output
    assert "no render cost" in res.output

    assert [c[0][0] for c in assembled] == [raw, raw]  # same footage, no new generation
    s = store.rows("SELECT * FROM scripts WHERE id=?", (sid,))[0]
    p = json.loads(s["payload"])
    assert s["hook"] == "How many burned 300 calories just now?"
    assert p["captions"] == ["new line"]

    rows = store.rows("SELECT * FROM renders WHERE script_id=? ORDER BY id", (sid,))
    assert len(rows) == 2
    new = rows[-1]
    assert new["cost_usd"] == 0.0 and new["model"] == "seedance"
    rp = json.loads(new["payload"])
    assert rp["recut"]["from_render"] == rid
    assert rp["recut"]["hook"] == "How many burned 300 calories just now?"
    assert Path(new["final_path"]).name == f"s{sid}.mp4"
    assert Path(new["post_path"]).name == f"s{sid}_clean.mp4"


def test_recut_keeps_the_script_text_when_no_options_given(tmp_path, monkeypatch):
    store, sid, rid, raw = _world(tmp_path, monkeypatch)
    def fake_assemble(clips, out, captions=None, sound=None):
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"cut moov")
        return Path(out)

    monkeypatch.setattr("marketing_agent.video.edit.assemble", fake_assemble)
    monkeypatch.setattr("marketing_agent.video.edit.probe_duration", lambda p: 12.0)
    monkeypatch.setattr("marketing_agent.video.edit.probe", lambda p: {"duration_s": 12.0})
    res = CliRunner().invoke(cli_mod.cli, ["recut", str(sid)])
    assert res.exit_code == 0, res.output
    s = store.rows("SELECT hook FROM scripts WHERE id=?", (sid,))[0]
    assert s["hook"] == "POV: cardio finally got fun"


def test_recut_without_a_render_refuses(tmp_path, monkeypatch):
    store, sid, rid, raw = _world(tmp_path, monkeypatch)
    with store.conn() as c:
        c.execute("DELETE FROM renders")
    res = CliRunner().invoke(cli_mod.cli, ["recut", str(sid)])
    assert res.exit_code != 0
    assert "no render to recut" in res.output


def test_recut_falls_back_to_the_api_when_no_local_file(tmp_path, monkeypatch):
    store, sid, rid, raw = _world(tmp_path, monkeypatch)
    raw.unlink()

    class R:
        status_code = 200
        content = b"clip with moov atom"

    monkeypatch.setattr("httpx.get", lambda url, timeout, follow_redirects: R())
    assembled = []
    def fake_assemble(clips, out, captions=None, sound=None):
        assembled.append(list(clips))
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"cut moov")
        return Path(out)

    monkeypatch.setattr("marketing_agent.video.edit.assemble", fake_assemble)
    monkeypatch.setattr("marketing_agent.video.edit.probe_duration", lambda p: 12.0)
    monkeypatch.setattr("marketing_agent.video.edit.probe", lambda p: {"duration_s": 12.0})
    res = CliRunner().invoke(cli_mod.cli, ["recut", str(sid), "--hook", "new"])
    assert res.exit_code == 0, res.output
    assert assembled[0][0].name == f"s{sid}_base.mp4"
    assert assembled[0][0].read_bytes() == b"clip with moov atom"
