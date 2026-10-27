"""Registering a post closes that clip's post-request run row, so the Learnings page stops
treating it as a cycle still going."""

import time

import pytest
from fastapi.testclient import TestClient

from marketing_agent import api


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MKT_DB", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("MKT_API_TOKEN", "t")
    return TestClient(api.app)


def test_registering_a_post_finishes_its_run_rows(client, tmp_path, monkeypatch):
    store = api._store()  # the API reads MKT_DB per request; share its file, not a fresh path
    handle = api.CAMPAIGN.account.handle
    now = int(time.time())
    base = {"created_at": now, "session_id": "s", "url": "u", "niche": "fitness", "product": "P"}
    mine = store.insert("runs", {**base, "note": f"post s7 from @{handle}"})
    retry = store.insert("runs", {**base, "note": f"post s7 from @{handle} (try 2)"})
    other = store.insert("runs", {**base, "note": f"post s8 from @{handle}"})
    cycle = store.insert("runs", {**base, "note": "5 clips at 720p"})
    monkeypatch.setattr(
        "marketing_agent.own.add_post",
        lambda store, url, caption, niche=None: {"id": "v", "script_id": 7, "url": url},
    )
    r = client.post(
        "/ours/posts",
        json={"url": "https://www.tiktok.com/@x/video/1", "caption": "c"},
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 200 and r.json()["script_id"] == 7
    rows = {x["id"]: x for x in store.rows("SELECT id, status, finished_at FROM runs")}
    assert rows[mine]["status"] == "ok" and rows[mine]["finished_at"]
    assert rows[retry]["status"] == "ok" and rows[retry]["finished_at"]
    assert rows[other]["finished_at"] is None
    assert rows[cycle]["finished_at"] is None
