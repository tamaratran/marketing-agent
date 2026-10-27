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
    seen = {}

    def fake_add_post(store, url, caption, niche=None, script_id=None):
        seen["script_id"] = script_id
        return {"id": "v", "script_id": script_id or 7, "url": url}

    monkeypatch.setattr("marketing_agent.own.add_post", fake_add_post)
    # The poster session names the clip it uploaded; no caption guess (two scripts can share
    # a hook, which is how s125 was registered without its script).
    r = client.post(
        "/ours/posts",
        json={"url": "https://www.tiktok.com/@x/video/1", "caption": "c", "script_id": 7},
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 200 and r.json()["script_id"] == 7 and seen["script_id"] == 7
    rows = {x["id"]: x for x in store.rows("SELECT id, status, finished_at FROM runs")}
    assert rows[mine]["status"] == "ok" and rows[mine]["finished_at"]
    assert rows[retry]["status"] == "ok" and rows[retry]["finished_at"]
    assert rows[other]["finished_at"] is None
    assert rows[cycle]["finished_at"] is None


def test_add_post_takes_the_script_id_over_a_caption_guess(tmp_path, monkeypatch):
    from marketing_agent import own
    from marketing_agent.store import Store

    store = Store(tmp_path / "db.sqlite")
    own.add_account(store, "acct", "tag", "P")
    monkeypatch.setattr(
        "marketing_agent.research.tiktok_browser.poll_public_stats", lambda url: None
    )
    monkeypatch.setattr(own, "match_script", lambda *a, **k: (95, 0.9))
    monkeypatch.setattr(own, "snapshot_creator", lambda store, author: None)
    res = own.add_post(
        store, "https://www.tiktok.com/@acct/video/42", "POV: cardio finally got fun", script_id=125
    )
    assert res["script_id"] == 125 and res["match"] == 1.0
    assert store.rows("SELECT script_id FROM videos WHERE id='42'")[0]["script_id"] == 125
    res = own.add_post(
        store, "https://www.tiktok.com/@acct/video/43", "POV: cardio finally got fun"
    )
    assert res["script_id"] == 95
