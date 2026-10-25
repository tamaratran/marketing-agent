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
    assert client.get("/creators").json() == []


def test_writes_need_token(client):
    assert client.post("/creators", json={"handle": "@a"}).status_code == 401
    os.environ.pop("MKT_API_TOKEN")
    assert client.post("/creators", json={"handle": "@a"}).status_code == 503


def test_creator_brief_status_and_payout_flow(client):
    assert (
        client.post("/creators", json={"handle": "@amy", "rate_per_1k": 1.5}, headers=AUTH).json()[
            "handle"
        ]
        == "amy"
    )
    assert client.get("/creators").json()[0]["handle"] == "amy"
    # a script to brief
    from marketing_agent.config import settings
    from marketing_agent.store import Store

    store = Store(settings.db_path)
    sid = store.insert(
        "scripts",
        {
            "concept_id": None,
            "product": "p",
            "created_at": 1,
            "hook": "h",
            "body": "",
            "demo_score": 5,
            "payload": '{"hook": "h", "captions": [], "body": "b", "demo_score": 5}',
        },
    )
    b = client.post("/briefs", json={"product": "p", "script_ids": [sid]}, headers=AUTH).json()
    assert client.post(f"/briefs/{b['id']}/status?status=approved", headers=AUTH).json()[
        "status"
    ] == ("approved")
    assert client.post(f"/briefs/{b['id']}/status?status=nope", headers=AUTH).status_code == 400
    assert client.get("/briefs").json()[0]["status"] == "approved"
    # a post and a payout without touching the network
    import marketing_agent.research.tiktok_browser as tb

    tb.poll_public_stats = lambda url: None
    p = client.post(
        "/posts",
        json={
            "creator": "amy",
            "url": "https://www.tiktok.com/@amy/video/123",
            "brief_id": b["id"],
        },
        headers=AUTH,
    ).json()
    assert p["video_id"] == "123"
    assert client.get("/payouts").json()[0]["creator"] == "amy"
    assert client.post("/payouts/123/paid", json={"amount_usd": 0.5}, headers=AUTH).json()["ok"]
    assert client.get("/payouts").json()[0]["paid_usd"] == 0.5


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
