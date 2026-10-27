"""Each clip's details (how it was made, what the file is) and its check against the winners."""

import json
import shutil
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from marketing_agent.status import clip_check


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_probe_reads_the_real_file(tmp_path):
    from marketing_agent.video.edit import probe

    out = tmp_path / "c.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=90x160:r=30:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=d=1",
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            str(out),
        ],
        check=True,
    )
    f = probe(out)
    assert (f["width"], f["height"], f["fps"], f["audio"]) == (90, 160, 30.0, True)
    assert 0.9 <= f["duration_s"] <= 1.1 and f["size_bytes"] > 0


def test_renders_carry_meta_and_facts_save_with_the_token(tmp_path, monkeypatch):
    from marketing_agent import api
    from marketing_agent.store import Store

    monkeypatch.setenv("MKT_API_TOKEN", "t")
    store = Store(tmp_path / "t.sqlite")
    store.migrate()
    monkeypatch.setattr(api, "_store", lambda: store)
    client = TestClient(api.app)
    now = int(time.time())
    cid = store.insert(
        "concepts",
        {"name": "TV follow-along", "niche": "fitness", "created_at": now, "payload": "{}"},
    )
    sid = store.insert(
        "scripts",
        {
            "concept_id": cid,
            "product": "p",
            "created_at": now,
            "hook": "After 8 minutes",
            "body": "0-2s: person faces the TV",
            "demo_score": 5,
            "payload": json.dumps(
                {"captions": ["After 8 minutes", " "], "sound": "Subway Surfers"}
            ),
        },
    )
    rid = store.insert(
        "renders",
        {
            "script_id": sid,
            "created_at": now,
            "model": "seedance-2.5",
            "prompt": "Vertical 9:16",
            "cost_usd": 5.5,
            "final_path": "s1.mp4",
            "payload": json.dumps(
                {
                    "input": {
                        "duration": 12,
                        "resolution": "720p",
                        "aspect_ratio": "9:16",
                        "generate_audio": True,
                    },
                    "result": {"seed": 7, "video": {"file_size": 100}},
                }
            ),
        },
    )
    m = client.get("/renders?niche=fitness").json()[0]["meta"]
    assert m["concept"] == "TV follow-along" and m["script"].startswith("0-2s")
    assert m["captions"] == ["After 8 minutes"] and m["sound"] == "Subway Surfers"
    assert m["generation"] == {
        "model": "seedance-2.5",
        "duration_s": 12,
        "resolution": "720p",
        "aspect_ratio": "9:16",
        "audio": True,
        "seed": 7,
        "size_bytes": 100,
        "cost_usd": 5.5,
    }
    assert m["file"] is None and m["prompt"] == "Vertical 9:16"

    facts = {"width": 1080, "height": 1920, "fps": 24.0, "duration_s": 12.0, "audio": True}
    assert client.post(f"/renders/{rid}/facts", json=facts).status_code == 401
    ok = client.post(f"/renders/{rid}/facts", json=facts, headers={"Authorization": "Bearer t"})
    assert ok.json() == {"saved": rid}
    assert client.get("/renders?niche=fitness").json()[0]["meta"]["file"] == facts


def test_clip_check_lists_spec_rubric_and_quality_rows():
    clip = {
        "meta": {"file": {"width": 1080, "height": 1920, "duration_s": 12.0, "audio": True}},
        "labels": {"tags": {"quality_issues": ["TV switches game at 2s"]}},
    }
    graded = {
        "differences": [{"label": "Movement", "ours": "slow", "winners": "fast"}],
        "grade": {"looks_fake": ["warped hands"], "hurt": ["no trending sound"]},
    }
    rows = clip_check(clip, graded, [8.0, 15.0, 30.0])
    assert [(r["item"], r["ok"]) for r in rows] == [
        ("Vertical 9:16", True),
        ("Has sound", True),
        ("Length like the winners", True),
        ("Movement", False),
        ("Looks fake", False),
        ("Hurt", False),
        ("Quality issue", False),
    ]
    assert rows[2]["want"] == "8 to 30s" and rows[3]["want"] == "fast"
    # before the file is probed, the generation settings stand in; one winner is too few to judge
    rows = clip_check(
        {"meta": {"generation": {"aspect_ratio": "16:9", "audio": False, "duration_s": 12}}},
        None,
        [10.0],
    )
    assert [(r["item"], r["ok"]) for r in rows] == [("Vertical 9:16", False), ("Has sound", False)]
