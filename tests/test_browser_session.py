"""One signed-in TikTok browser across sessions: save/restore cookies through the API."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from marketing_agent import api
from marketing_agent.orchestrator import post_prompt
from marketing_agent.research import tiktok_auth as auth

TT = {"name": "sessionid", "value": "x", "domain": ".tiktok.com", "path": "/"}
OTHER = {"name": "g", "value": "y", "domain": ".google.com", "path": "/"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MKT_DB", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("MKT_API_TOKEN", "t")
    monkeypatch.setenv("MKT_SESSION_KEY", Fernet.generate_key().decode())
    return TestClient(api.app)


def test_session_round_trip_is_encrypted_at_rest(client, tmp_path):
    h = {"Authorization": "Bearer t"}
    assert client.get("/browser/session", headers=h).status_code == 404
    r = client.put("/browser/session", json={"cookies": [TT]}, headers=h)
    assert r.status_code == 200 and r.json()["cookies"] == 1
    raw = (tmp_path / "browser_session.enc").read_bytes()
    assert b"sessionid" not in raw
    got = client.get("/browser/session", headers=h).json()
    assert got["cookies"] == [TT] and got["saved_at"] > 0


def test_session_needs_token_and_key(client, monkeypatch):
    assert client.get("/browser/session").status_code == 401
    assert client.put("/browser/session", json={"cookies": [TT]}).status_code == 401
    monkeypatch.delenv("MKT_SESSION_KEY")
    r = client.put(
        "/browser/session", json={"cookies": [TT]}, headers={"Authorization": "Bearer t"}
    )
    assert r.status_code == 503


def _chrome(monkeypatch, signed_in: list[bool]):
    context = SimpleNamespace(
        new_page=AsyncMock(return_value=SimpleNamespace(close=AsyncMock())),
        cookies=AsyncMock(return_value=[TT, OTHER]),
        clear_cookies=AsyncMock(),
        add_cookies=AsyncMock(),
    )
    browser = SimpleNamespace(contexts=[context])
    p = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=AsyncMock(return_value=browser)))
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=p)
    manager.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(auth, "async_playwright", lambda: manager)
    monkeypatch.setattr(auth, "_verify_profile", AsyncMock(side_effect=signed_in))
    return context


def test_export_only_tiktok_cookies_from_a_verified_login(monkeypatch):
    _chrome(monkeypatch, [True])
    assert asyncio.run(auth.export_session("cdp", "kriscaroll")) == [TT]
    _chrome(monkeypatch, [False])
    with pytest.raises(auth.LoginRequired):
        asyncio.run(auth.export_session("cdp", "kriscaroll"))


def test_import_loads_cookies_then_checks_the_profile(monkeypatch):
    ctx = _chrome(monkeypatch, [False, True])
    assert asyncio.run(auth.import_session("cdp", [TT, OTHER], "kriscaroll")) is True
    ctx.clear_cookies.assert_awaited_once()
    ctx.add_cookies.assert_awaited_once_with([TT])
    ctx = _chrome(monkeypatch, [True])
    assert asyncio.run(auth.import_session("cdp", [TT], "kriscaroll")) is True
    ctx.add_cookies.assert_not_awaited()
    with pytest.raises(auth.LoginRequired):
        asyncio.run(auth.import_session("cdp", [OTHER], "kriscaroll"))


def test_poster_prompt_restores_before_login_and_saves_after():
    p = post_prompt(1, "u.mp4", ["a"], "cap", "", None, "kriscaroll", "https://api")
    assert p.index("mkt browser restore") < p.index("mkt own login")
    assert p.index("tiktokstudio/upload") < p.index("Run `mkt browser save`")
    assert "export cookies" not in p
