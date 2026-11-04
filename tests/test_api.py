import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MKT_DB", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("MKT_API_TOKEN", "t")
    from marketing_agent import api

    return TestClient(api.app)


AUTH = {"Authorization": "Bearer t"}


def test_reads_work_on_empty_db(client):
    assert client.get("/health").json()["ok"] is True
    o = client.get("/overview").json()
    assert o["videos"] == 0 and o["hooks"] == []
    assert client.get("/concepts").json() == []


def test_writes_need_token(client):
    assert client.post("/analyze").status_code == 401
    os.environ.pop("MKT_API_TOKEN")
    assert client.post("/analyze").status_code == 503


def test_db_export_import_roundtrip(client):
    from marketing_agent.config import settings

    client.get("/overview")
    exported = client.get("/db")
    assert exported.status_code == 200 and exported.content.startswith(b"SQLite format 3")
    assert client.post("/db", content=b"nope", headers=AUTH).status_code == 400
    r = client.post("/db", content=exported.content, headers=AUTH)
    assert r.json()["bytes"] == len(exported.content)
    assert settings.db_path.read_bytes() == exported.content


def test_site_reads_are_niche_scoped_and_honest(client):
    from marketing_agent import api

    store = api._store()
    store.set_niche_tags("wearables", ["smartring"])
    c_w = store.insert(
        "concepts",
        {
            "niche": "wearables",
            "name": "Demo",
            "description": "",
            "early_score": 1,
            "created_at": 1,
        },
    )
    c_t = store.insert(
        "concepts",
        {"niche": "tanning", "name": "Tan", "description": "", "early_score": 1, "created_at": 1},
    )
    now = int(__import__("time").time())
    s_w = store.insert(
        "scripts",
        {
            "concept_id": c_w,
            "product": "ring",
            "created_at": now,
            "hook": "Text on screen: before vs after",
            "body": "",
            "demo_score": 5,
            "payload": "{}",
        },
    )
    s_t = store.insert(
        "scripts",
        {
            "concept_id": c_t,
            "product": "tan",
            "created_at": now,
            "hook": "tan",
            "body": "",
            "demo_score": 5,
            "payload": "{}",
        },
    )
    store.insert(
        "renders",
        {
            "script_id": s_w,
            "created_at": now,
            "model": "stub",
            "cost_usd": 0,
            "final_path": "x.mp4",
        },
    )
    store.insert(
        "renders",
        {
            "script_id": s_w,
            "created_at": now,
            "model": "seedance",
            "cost_usd": 1,
            "final_path": "y.mp4",
        },
    )
    store.insert(
        "renders",
        {
            "script_id": s_t,
            "created_at": now,
            "model": "seedance",
            "cost_usd": 1,
            "final_path": "z.mp4",
        },
    )
    scripts = client.get("/scripts?niche=wearables").json()
    assert [s["id"] for s in scripts] == [s_w] and scripts[0]["hook"] == "before vs after"
    renders = client.get("/renders?niche=wearables").json()
    assert [r["final_path"] for r in renders] == ["y.mp4"] and renders[0][
        "hook"
    ] == "before vs after"
    assert store.niche_tags("wearables") == ["smartring"]


def test_video_and_creator_detail(client):
    from marketing_agent import api

    store = api._store()
    now = int(__import__("time").time())
    store.upsert_video(
        {
            "id": "v1",
            "url": "https://www.tiktok.com/@bob/video/v1",
            "author": "bob",
            "followers": 10,
            "create_time": now - 3600,
            "duration": 9,
            "desc": "d #x",
            "music": "m",
            "hashtags": ["x"],
            "source_tag": "smartring",
            "views": 5,
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "saves": 0,
        }
    )
    d = client.get("/videos/v1").json()
    assert d["video"]["author"] == "bob" and len(d["observations"]) == 1 and d["tags"] is None
    c = client.get("/creators/bob").json()
    assert c["videos"][0]["id"] == "v1"
    assert client.get("/videos/nope").status_code == 404
    assert client.post("/repoll").status_code in (401, 503)


def test_run_cycle_with_empty_body_uses_api_config(client, monkeypatch):
    """The site's Run cycle button posts {} and the API fills in its MKT_* config."""
    from marketing_agent import orchestrator

    seen = {}

    def fake_create(self, prompt, **kw):
        seen["prompt"], seen["kw"] = prompt, kw
        return {"session_id": "devin-1", "url": "https://app.devin.ai/sessions/1"}

    monkeypatch.setattr(orchestrator.DevinClient, "__init__", lambda self: None)
    monkeypatch.setattr(orchestrator.DevinClient, "create_session", fake_create)
    r = client.post("/runs", headers=AUTH)
    assert r.status_code == 200 and r.json()["session_id"] == "devin-1"
    assert "--renders 5 --resolution 720p" in seen["prompt"]
    assert seen["kw"]["max_acu_limit"] == 10
    run = client.get("/runs").json()[0]
    assert run["note"] == "5 clips at 720p" and run["url"].endswith("/1")
    r = client.post(
        "/runs",
        headers=AUTH,
        json={"renders": 2, "resolution": "1080p", "refs": ["https://x/i.png"]},
    )
    assert r.status_code == 200
    assert '--renders 2 --resolution 1080p --ref "https://x/i.png"' in seen["prompt"]


def test_campaign_endpoint_is_the_run_config(client):
    """The Runs page shows exactly what an empty POST /runs would run."""
    from marketing_agent.api import RunIn

    c = client.get("/campaign").json()
    assert c["account"]["handle"] == "kriscaroll"
    assert c["product"]["name"] == "Immersive Workout"
    body = RunIn()
    assert body.niche == c["niche"]["name"] and body.tags == c["niche"]["hashtags"]
    assert body.refs == c["product"]["references"] and body.renders == c["cycle"]["clips"]


def test_logic_lists_scored_videos_and_picker_constants(client):
    from marketing_agent import policy

    out = client.get("/logic").json()
    assert out["explore_sd"] == policy.EXPLORE_SD and out["format_edge"] == policy.FORMAT_EDGE
    assert out["format_prior"] is None
    assert isinstance(out["videos"], list)


def test_learnings_endpoints(client):
    assert client.get("/learnings").json() == []
    md = client.get("/learnings.md")
    assert md.status_code == 200 and md.text.startswith("# Learnings")


def test_renders_carry_the_text_to_type_into_tiktok(tmp_path):
    import json
    import time

    from marketing_agent import api
    from marketing_agent.store import Store

    store = Store(tmp_path / "t.sqlite")
    store.migrate()
    api._store = lambda: store  # noqa: SLF001
    client = TestClient(api.app)
    now = int(time.time())
    cid = store.insert(
        "concepts", {"name": "c", "niche": "fitness", "created_at": now, "payload": "{}"}
    )
    sid = store.insert(
        "scripts",
        {
            "concept_id": cid,
            "product": "p",
            "created_at": now,
            "hook": "Text on screen: POV: cardio finally got fun",
            "body": "",
            "demo_score": 5,
            "payload": json.dumps(
                {"captions": ["POV: cardio", "finally got fun", " ", "free app on iPhone"]}
            ),
        },
    )
    store.insert(
        "renders",
        {
            "script_id": sid,
            "created_at": now,
            "model": "seedance",
            "cost_usd": 1,
            "final_path": "s1.mp4",
            "post_path": "s1_clean.mp4",
        },
    )
    old = store.insert(
        "renders",
        {"script_id": sid, "created_at": now - 1, "model": "seedance", "final_path": "s0.mp4"},
    )
    rows = client.get("/renders?niche=fitness").json()
    assert rows[0]["post_path"] == "s1_clean.mp4"
    assert rows[0]["post_text"] == ["POV: cardio finally got fun", "free app on iPhone"]
    assert [r["id"] for r in rows][1] == old and rows[1]["post_path"] is None


def test_post_button_starts_one_posting_session(client, monkeypatch):
    """Post on a clip starts a Devin session told to upload that clip from our account, add the
    text with TikTok's text tool and register the post; pressing twice does not start another."""
    import json
    import time

    from marketing_agent import api, orchestrator

    seen = {"created": 0, "messages": []}
    state = {"status": "finished"}

    def fake_create(self, prompt, **kw):
        seen["prompt"], seen["kw"] = prompt, kw
        seen["created"] += 1
        return {"session_id": "devin-p", "url": "https://app.devin.ai/sessions/p"}

    def fake_get(self, session_id):
        if state["status"] == "gone":
            raise RuntimeError("Devin API 404")
        return {"session_id": session_id, "status": state["status"]}

    def fake_message(self, session_id, message):
        seen["messages"].append((session_id, message))
        return {}

    monkeypatch.setattr(orchestrator.DevinClient, "__init__", lambda self: None)
    monkeypatch.setattr(orchestrator.DevinClient, "create_session", fake_create)
    monkeypatch.setattr(orchestrator.DevinClient, "get_session", fake_get)
    monkeypatch.setattr(orchestrator.DevinClient, "send_message", fake_message)
    store = api._store()  # noqa: SLF001
    now = int(time.time())
    cid = store.insert(
        "concepts", {"name": "c", "niche": api.DEFAULT_NICHE, "created_at": now, "payload": "{}"}
    )
    sid = store.insert(
        "scripts",
        {
            "concept_id": cid,
            "product": "p",
            "created_at": now,
            "hook": "POV: cardio finally got fun",
            "body": "",
            "demo_score": 5,
            "payload": json.dumps(
                {
                    "captions": ["POV: cardio", "finally got fun"],
                    "sound": "SUBWAY SURFERS",
                    "sound_id": "77",
                }
            ),
        },
    )
    assert client.post(f"/renders/{sid}/post", headers=AUTH).status_code == 404
    rid = store.insert(
        "renders",
        {"script_id": sid, "created_at": now, "model": "seedance", "final_path": "s1.mp4"},
    )
    r = client.post(f"/renders/{sid}/post", headers=AUTH)
    assert r.status_code == 400 and "clean copy" in r.text
    with store.conn() as c:
        c.execute("UPDATE renders SET post_path='s1_clean.mp4' WHERE id=?", (rid,))
    r = client.post(f"/renders/{sid}/post", headers=AUTH)
    assert r.status_code == 200 and r.json()["session_id"] == "devin-p"
    p = seen["prompt"]
    assert (
        f"/s{sid}_clean.mp4" in p and "  1. POV: cardio finally got fun" in p and "  2. " not in p
    )
    assert "SUBWAY SURFERS (https://www.tiktok.com/music/x-77)" in p
    assert "/ours/posts" in p and "do not toggle it" in p
    assert seen["kw"]["title"] == "mkt poster @" + api.CAMPAIGN.account.handle
    assert "poster session" in p and seen["created"] == 1 and seen["messages"] == []
    again = client.post(f"/renders/{sid}/post", headers=AUTH).json()
    assert again["already"] is True and again["url"].endswith("/p")
    rend = next(
        r for r in client.get(f"/renders?niche={api.DEFAULT_NICHE}").json() if r["script_id"] == sid
    )
    assert rend["post_session_url"].endswith("/p") and rend["post_requested_at"]
    assert client.get("/runs").json()[0]["note"].startswith(f"post s{sid}")

    def clip(hook):
        s2 = store.insert(
            "scripts",
            {
                "concept_id": cid,
                "product": "p",
                "created_at": now,
                "hook": hook,
                "body": "",
                "demo_score": 5,
                "payload": "{}",
            },
        )
        store.insert(
            "renders",
            {
                "script_id": s2,
                "created_at": now,
                "model": "seedance",
                "final_path": f"s{s2}.mp4",
                "post_path": f"s{s2}_clean.mp4",
            },
        )
        return s2

    # The next clip goes to the same poster session as a message: one TikTok login for all posts.
    s2 = clip("Second clip")
    r = client.post(f"/renders/{s2}/post", headers=AUTH).json()
    assert r["reused"] is True and r["session_id"] == "devin-p" and seen["created"] == 1
    assert len(seen["messages"]) == 1 and f"/s{s2}_clean.mp4" in seen["messages"][0][1]

    # When that session is gone, a new poster session is started and remembered.
    state["status"] = "gone"
    s3 = clip("Third clip")
    r = client.post(f"/renders/{s3}/post", headers=AUTH).json()
    assert r["reused"] is False and seen["created"] == 2 and len(seen["messages"]) == 1
    state["status"] = "terminated"
    s4 = clip("Fourth clip")
    r = client.post(f"/renders/{s4}/post", headers=AUTH).json()
    assert r["reused"] is False and seen["created"] == 3

    # A clip whose hand-off is an hour old with no registered post can be handed over again;
    # one with a registered post cannot.
    with store.conn() as c:
        c.execute(
            "UPDATE renders SET post_requested_at=? WHERE script_id IN (?,?)", (now - 4000, s3, s4)
        )
        c.execute(
            """INSERT INTO videos (id,url,author,ours,script_id,first_seen,create_time)
               VALUES ('v4','u','a',1,?,?,?)""",
            (s4, now, now),
        )
    state["status"] = "finished"
    assert client.post(f"/renders/{s3}/post", headers=AUTH).json()["reused"] is True
    assert client.post(f"/renders/{s4}/post", headers=AUTH).json()["already"] is True

    # The API hands stale clips back on its own, at most MAX_POST_ATTEMPTS times each; a person
    # pressing Post is not capped. The posted clip (s4) and fresh hand-offs are left alone.
    n_msgs = len(seen["messages"])
    with store.conn() as c:
        c.execute(
            "UPDATE renders SET post_requested_at=?, post_attempts=? WHERE script_id=?",
            (now - 4000, 1, s3),
        )
        c.execute(
            "UPDATE renders SET post_requested_at=?, post_attempts=? WHERE script_id=?",
            (now - 4000, api.MAX_POST_ATTEMPTS, s2),
        )
    r = client.post("/renders/retry", headers=AUTH).json()
    assert r["retried"] == [s3] and len(seen["messages"]) == n_msgs + 1
    assert client.post("/renders/retry", headers=AUTH).json()["retried"] == []
    rend = {x["script_id"]: x for x in client.get(f"/renders?niche={api.DEFAULT_NICHE}").json()}
    assert rend[s3]["post_attempts"] == 2 and rend[s2]["post_attempts"] == api.MAX_POST_ATTEMPTS
    by_hand = client.post(f"/renders/{s2}/post", headers=AUTH).json()
    assert by_hand["reused"] is True and by_hand["attempt"] == api.MAX_POST_ATTEMPTS + 1


def test_concepts_carry_pick_share_and_example_lift(client):
    import json
    import time

    from marketing_agent import api

    store = api._store()
    store.upsert_video(
        {
            "id": "v1",
            "url": "https://www.tiktok.com/@a/video/v1",
            "author": "a",
            "followers": 100,
            "create_time": int(time.time()) - 3600,
            "duration": 10,
            "desc": "",
            "music": "",
            "hashtags": [],
            "source_tag": "fitness",
            "views": 500,
        }
    )
    for name in ("A", "B"):
        store.insert(
            "concepts",
            {
                "niche": "fitness",
                "created_at": int(time.time()),
                "name": name,
                "description": "d",
                "video_ids": json.dumps(["v1"]),
                "early_score": 5.0,
                "payload": "{}",
            },
        )
    rows = client.get("/concepts?niche=fitness").json()
    assert abs(sum(c["pick_share"] for c in rows) - 1) < 1e-6
    ours = [c for c in rows if c["name"] in ("A", "B")]
    assert len(ours) == 2
    assert all("reward" in e for c in ours for e in c["examples"])


def test_tags_merge_row_by_row(client, monkeypatch):
    from pathlib import Path

    from marketing_agent import api
    from marketing_agent.store import Store

    store = Store(Path(os.environ["MKT_DB"]))
    monkeypatch.setattr(api, "_store", lambda: store)
    store.insert("videos", {"id": "v1", "url": "u", "author": "a"})
    rows = [
        {
            "video_id": "v1",
            "model": "gemini",
            "payload": {"tags": {"hook_type": "text_on_screen"}, "run": {}},
        },
        {"video_id": "nope", "model": "gemini", "payload": {}},
    ]
    assert client.post("/tags", json=rows).status_code == 401
    r = client.post("/tags", json=rows, headers=AUTH).json()
    assert r == {"saved": 1, "unknown": ["nope"]}
    assert store.tags_for(["v1"])["v1"]["tags"]["hook_type"] == "text_on_screen"


def test_clip_and_poster_files_roundtrip(client, tmp_path, monkeypatch):
    from marketing_agent import api

    monkeypatch.setattr(api.settings, "data_dir", tmp_path / "data")
    assert client.get("/files").json() == []
    assert client.put("/files/renders/s95.mp4", content=b"ftyp moov").status_code == 401
    assert (
        client.put("/files/renders/s95.mp4", content=b"ftypisom", headers=AUTH).status_code == 400
    )
    r = client.put("/files/renders/s95.mp4", content=b"ftyp moov", headers=AUTH)
    assert r.status_code == 200 and r.json()["bytes"] == 9
    assert client.put("/files/frames/s95.jpg", content=b"jpg", headers=AUTH).status_code == 200
    assert client.put("/files/renders/evil.sh", content=b"x", headers=AUTH).status_code == 400
    assert client.put("/files/other/s1.mp4", content=b"x", headers=AUTH).status_code == 400
    got = client.get("/files/renders/s95.mp4")
    assert got.status_code == 200 and got.content == b"ftyp moov"
    assert got.headers["content-type"].startswith("video/mp4")
    assert client.get("/files/renders/s96.mp4").status_code == 404
    assert [(f["kind"], f["name"], f["bytes"]) for f in client.get("/files").json()] == [
        ("renders", "s95.mp4", 9),
        ("frames", "s95.jpg", 3),
    ]
