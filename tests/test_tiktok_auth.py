import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from marketing_agent.research import tiktok_auth as auth


def browser_mock(monkeypatch):
    page = MagicMock()
    page.url = "https://www.tiktok.com/login/phone-or-email/email"
    page.goto = AsyncMock()
    page.close = AsyncMock()
    page.wait_for_url = AsyncMock()
    page.locator.return_value.fill = AsyncMock()
    page.get_by_role.return_value.click = AsyncMock()
    context = SimpleNamespace(new_page=AsyncMock(return_value=page))
    browser = SimpleNamespace(contexts=[context])
    p = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=AsyncMock(return_value=browser)))
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=p)
    manager.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(auth, "async_playwright", lambda: manager)
    monkeypatch.setenv("TIKTOK_POST_HANDLE", "@testaccount")
    monkeypatch.delenv("TIKTOK_POST_PASSWORD", raising=False)
    return page


def test_handle_validation_and_profile_links():
    assert auth.normalize_handle(" @TestAccount ") == "testaccount"
    assert auth.profile_handle("/@TestAccount?lang=en") == "testaccount"
    assert auth.profile_handle("https://www.tiktok.com/@testaccount") == "testaccount"
    assert auth.profile_handle("/login") is None
    assert auth.profile_handle("/@") is None  # logged-out nav link
    for bad in ("", "test@gmail.com", "https://example.com/", "../user", "user/pass"):
        with pytest.raises(auth.LoginRequired):
            auth.normalize_handle(bad)


def test_existing_login_never_submits_password(monkeypatch):
    page = browser_mock(monkeypatch)
    monkeypatch.setattr(auth, "_verify_profile", AsyncMock(return_value=True))
    assert asyncio.run(auth.ensure_login("cdp")) == "reused"
    page.locator.assert_not_called()
    page.close.assert_awaited_once()


def test_missing_password_fails_without_login_attempt(monkeypatch):
    page = browser_mock(monkeypatch)
    monkeypatch.setattr(auth, "_verify_profile", AsyncMock(return_value=False))
    with pytest.raises(auth.LoginRequired, match="protected secret"):
        asyncio.run(auth.ensure_login("cdp"))
    page.get_by_role.assert_not_called()
    page.close.assert_awaited_once()


def test_password_submission_verifies_identity_after_redirect(monkeypatch):
    page = browser_mock(monkeypatch)
    monkeypatch.setenv("TIKTOK_POST_PASSWORD", "unit-test-password")
    verify = AsyncMock(side_effect=[False, True])
    monkeypatch.setattr(auth, "_verify_profile", verify)
    assert asyncio.run(auth.ensure_login("cdp")) == "logged_in"
    page.get_by_role.return_value.click.assert_awaited_once()
    assert verify.await_count == 2
    page.close.assert_awaited_once()


def test_verification_challenge_leaves_tab_and_never_retries(monkeypatch):
    page = browser_mock(monkeypatch)
    monkeypatch.setenv("TIKTOK_POST_PASSWORD", "unit-test-password")
    monkeypatch.setattr(auth, "_verify_profile", AsyncMock(return_value=False))
    page.wait_for_url.side_effect = PlaywrightTimeoutError("private UI detail")
    with pytest.raises(auth.LoginRequired, match="verification") as exc:
        asyncio.run(auth.ensure_login("cdp"))
    assert "unit-test-password" not in str(exc.value)
    assert "private UI detail" not in str(exc.value)
    page.get_by_role.return_value.click.assert_awaited_once()
    page.close.assert_not_awaited()


def test_wrong_identity_does_not_change_account(monkeypatch):
    page = browser_mock(monkeypatch)
    page.locator.return_value.first.wait_for = AsyncMock()
    monkeypatch.setattr(auth, "_identity", AsyncMock(return_value="anotheraccount"))
    with pytest.raises(auth.LoginRequired, match="different TikTok account"):
        asyncio.run(auth.ensure_login("cdp"))
    page.get_by_role.assert_not_called()
    page.close.assert_awaited_once()


def test_unexpected_redirect_does_not_receive_password(monkeypatch):
    page = browser_mock(monkeypatch)
    page.url = "https://example.com/login"
    monkeypatch.setenv("TIKTOK_POST_PASSWORD", "unit-test-password")
    monkeypatch.setattr(auth, "_verify_profile", AsyncMock(return_value=False))
    with pytest.raises(auth.LoginRequired, match="redirected unexpectedly"):
        asyncio.run(auth.ensure_login("cdp"))
    page.locator.assert_not_called()


def test_browser_error_does_not_leak_fill_values(monkeypatch):
    from playwright.async_api import Error

    page = browser_mock(monkeypatch)
    monkeypatch.setenv("TIKTOK_POST_PASSWORD", "unit-test-password")
    monkeypatch.setattr(auth, "_verify_profile", AsyncMock(return_value=False))
    page.locator.return_value.fill.side_effect = Error('fill("unit-test-password")')
    with pytest.raises(auth.LoginRequired, match="interaction failed") as exc:
        asyncio.run(auth.ensure_login("cdp"))
    assert "unit-test-password" not in str(exc.value)


def test_profile_requires_readable_feed_and_filters_authors(monkeypatch):
    from marketing_agent.research import tiktok_browser

    scrape = AsyncMock(return_value=[{"author": "TestAccount"}, {"author": "recommended"}])
    monkeypatch.setattr(tiktok_browser, "_scrape_items", scrape)
    rows = asyncio.run(tiktok_browser.scrape_profile("@TestAccount", "cdp"))
    assert rows == [{"author": "TestAccount"}]
    assert scrape.call_args.kwargs["require_response"] is True


def test_wrong_profile_feed_is_not_reported_as_empty(monkeypatch):
    from marketing_agent.research import tiktok_browser

    monkeypatch.setattr(
        tiktok_browser, "_scrape_items", AsyncMock(return_value=[{"author": "someoneelse"}])
    )
    with pytest.raises(RuntimeError, match="different profile"):
        asyncio.run(tiktok_browser.scrape_profile("testaccount", "cdp"))


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"statusCode": 0, "itemList": []}, []),
        ({"statusCode": 10201}, None),
        ({"unrelated": True}, None),
    ],
)
def test_missing_profile_feed_is_not_empty_account(monkeypatch, payload, expected):
    from marketing_agent.research import tiktok_browser

    page = browser_mock(monkeypatch)
    handler = {}
    page.on.side_effect = lambda event, callback: handler.update(callback=callback)

    async def goto(*args, **kwargs):
        response = SimpleNamespace(
            url="https://www.tiktok.com/api/post/item_list/", json=AsyncMock(return_value=payload)
        )
        handler["callback"](response)

    page.goto = goto
    page.wait_for_timeout = AsyncMock()
    page.mouse.wheel = AsyncMock()
    monkeypatch.setattr(tiktok_browser, "async_playwright", auth.async_playwright)
    call = tiktok_browser._scrape_items(
        "https://www.tiktok.com/@testaccount", "/api/post/item_list", "profile", "cdp", 0, True
    )
    if expected is None:
        with pytest.raises(RuntimeError, match="not a verified empty account"):
            asyncio.run(call)
    else:
        assert asyncio.run(call) == expected
    page.close.assert_awaited_once()
