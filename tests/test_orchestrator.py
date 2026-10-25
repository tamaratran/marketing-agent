import json

import httpx

from marketing_agent.orchestrator import DailyReport, DevinClient, daily_prompt
from marketing_agent.store import Store


def _client(handler):
    return DevinClient(api_key="k", org_id="org-x", transport=httpx.MockTransport(handler))


def test_create_session_hits_v3_with_bearer_and_repo():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"] = str(req.url)
        seen["auth"] = req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"session_id": "devin-1", "url": "https://x/1"})

    s = _client(handler).create_session("do it", title="t", repos=["o/r"], max_acu_limit=5)
    assert s["session_id"] == "devin-1"
    assert seen["url"].endswith("/v3/organizations/org-x/sessions")
    assert seen["auth"] == "Bearer k"
    assert seen["body"] == {"prompt": "do it", "title": "t", "repos": ["o/r"], "max_acu_limit": 5}


def test_wait_returns_when_session_settles():
    calls = {"n": 0}

    def handler(req: httpx.Request):
        calls["n"] += 1
        detail = "working" if calls["n"] < 3 else "finished"
        return httpx.Response(200, json={"status": "running", "status_detail": detail})

    s = _client(handler).wait("devin-1", poll_s=0)
    assert s["status_detail"] == "finished" and calls["n"] == 3


def test_api_error_is_raised_with_status():
    def handler(req: httpx.Request):
        return httpx.Response(401, json={"title": "Unauthorized"})

    try:
        _client(handler).get_session("devin-1")
    except RuntimeError as e:
        assert "401" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


def test_daily_prompt_is_self_contained():
    p = daily_prompt("wearables", ["smartring", "whoop"], "a smart ring", renders=2, repo="o/r")
    assert "Repo: o/r" in p
    assert 'mkt daily wearables smartring whoop --product "a smart ring" --renders 2' in p
    assert "MKT_DB=" in p and "git push origin HEAD:state" in p
    assert "never post to TikTok" in p


def test_daily_report_writes_markdown_on_empty_store(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    rep = DailyReport("wearables", "a smart ring")
    rep.ok("run", 12.3, "ok")
    rep.fail("render", RuntimeError("FAL_KEY not set"))
    rep.skip("poll_posts", "nothing tracked")
    out = rep.write(tmp_path / "r" / "today.md", store)
    text = out.read_text()
    assert rep.failed == ["render"]
    assert "| render | failed | 0 | RuntimeError: FAL_KEY not set |" in text
    assert "## Scoreboard" in text and "## Policy" in text
