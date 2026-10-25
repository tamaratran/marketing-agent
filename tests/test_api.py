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
