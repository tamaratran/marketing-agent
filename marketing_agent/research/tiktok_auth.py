"""Use the user's Chrome session; never automate verification challenges.

The signed-in session can be saved (cookies only, for tiktok.com) and loaded into another Chrome,
so a poster session on a fresh VM is the same signed-in browser to TikTok instead of a new login,
which TikTok throttles. The saved cookies go only to the API, encrypted at rest, over the token."""

import asyncio
import os
import re
from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

PROFILE_LINK = 'a[data-e2e="nav-profile"]'


class LoginRequired(RuntimeError):
    pass


def normalize_handle(handle: str) -> str:
    handle = handle.strip().lstrip("@").lower()
    if not re.fullmatch(r"[a-z0-9_.]+", handle):
        raise LoginRequired("Set TIKTOK_POST_HANDLE to a TikTok username, not an email or URL.")
    return handle


def profile_handle(href: str | None) -> str | None:
    path = urlsplit(href or "").path
    return (path[2:].lower() or None) if path.startswith("/@") else None  # logged out: "/@"


async def _identity(page) -> str | None:
    links = page.locator(PROFILE_LINK)
    if await links.count():
        return profile_handle(await links.first.get_attribute("href"))
    return None


async def _verify_profile(page, handle: str) -> bool:
    await page.goto(
        f"https://www.tiktok.com/@{handle}", wait_until="domcontentloaded", timeout=45000
    )
    try:
        await page.locator(
            f'{PROFILE_LINK}, button[data-e2e="top-login-button"], '
            'button[data-e2e="side-nav-login-button"]'
        ).first.wait_for(timeout=15000)
    except PlaywrightTimeoutError:
        pass
    identity = await _identity(page)
    if identity is not None and identity != handle:
        raise LoginRequired(
            "Chrome is signed into a different TikTok account. Switch accounts manually; "
            "the script will not log anyone out."
        )
    if identity != handle:
        return False
    try:
        await page.locator('[data-e2e="edit-profile-entrance"]').wait_for(timeout=15000)
    except PlaywrightTimeoutError:
        return False
    return True


async def ensure_login(cdp_url: str, handle: str | None = None) -> str:
    """Reuse a verified login or submit credentials once. Leave 2FA/CAPTCHA to the human."""
    handle = normalize_handle(handle or os.environ.get("TIKTOK_POST_HANDLE", ""))
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp_url)
        page = await browser.contexts[0].new_page()
        leave_open = False
        try:
            if await _verify_profile(page, handle):
                return "reused"
            password = os.environ.get("TIKTOK_POST_PASSWORD")
            if not password:
                raise LoginRequired(
                    "No verified TikTok session. Log in in Chrome or supply "
                    "TIKTOK_POST_PASSWORD as a protected secret, then rerun."
                )
            await page.goto(
                "https://www.tiktok.com/login/phone-or-email/email",
                wait_until="domcontentloaded",
                timeout=45000,
            )
            if urlsplit(page.url).hostname != "www.tiktok.com":
                raise LoginRequired("TikTok login redirected unexpectedly; no credentials entered.")
            await page.locator('input[name="username"]').fill(handle)
            await page.locator('input[type="password"]').fill(password)
            await page.get_by_role("button", name="Log in", exact=True).click()
            leave_open = True
            try:
                await page.wait_for_url(
                    lambda url: (
                        urlsplit(url).hostname == "www.tiktok.com"
                        and "/login" not in urlsplit(url).path
                    ),
                    timeout=20000,
                )
            except PlaywrightTimeoutError:
                raise LoginRequired(
                    "TikTok login needs attention. Check the open Chrome tab for verification, "
                    "CAPTCHA or a login error, complete it manually, then rerun. "
                    "No automatic retries or verification bypasses were attempted."
                ) from None
            if not await _verify_profile(page, handle):
                raise LoginRequired("TikTok did not confirm the expected login. Check Chrome.")
            leave_open = False
            return "logged_in"
        except PlaywrightTimeoutError:
            raise LoginRequired("TikTok did not finish loading. Check Chrome and rerun.") from None
        except PlaywrightError:
            raise LoginRequired(
                "TikTok browser interaction failed. Check Chrome and rerun."
            ) from None
        finally:
            if not leave_open:
                await page.close()


def ensure_login_sync(cdp_url: str, handle: str | None = None) -> str:
    return asyncio.run(ensure_login(cdp_url, handle))


def _is_tiktok(cookie: dict) -> bool:
    return cookie.get("domain", "").lstrip(".").endswith("tiktok.com")


async def export_session(cdp_url: str, handle: str | None = None) -> list[dict]:
    """The tiktok.com cookies of a Chrome verified to be signed in as our handle."""
    handle = normalize_handle(handle or os.environ.get("TIKTOK_POST_HANDLE", ""))
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0]
        page = await context.new_page()
        try:
            if not await _verify_profile(page, handle):
                raise LoginRequired(f"Chrome is not signed in as @{handle}; nothing saved.")
            cookies = [c for c in await context.cookies() if _is_tiktok(c)]
        finally:
            await page.close()
    if not cookies:
        raise LoginRequired("No tiktok.com cookies in this Chrome; nothing saved.")
    return cookies


async def import_session(cdp_url: str, cookies: list[dict], handle: str | None = None) -> bool:
    """Load saved cookies into this Chrome and say whether TikTok now shows us signed in."""
    handle = normalize_handle(handle or os.environ.get("TIKTOK_POST_HANDLE", ""))
    cookies = [c for c in cookies if _is_tiktok(c)]
    if not cookies:
        raise LoginRequired("Saved session has no tiktok.com cookies.")
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0]
        page = await context.new_page()
        try:
            if await _verify_profile(page, handle):
                return True
            await context.clear_cookies()
            await context.add_cookies(cookies)
            return await _verify_profile(page, handle)
        finally:
            await page.close()


def export_session_sync(cdp_url: str, handle: str | None = None) -> list[dict]:
    return asyncio.run(export_session(cdp_url, handle))


def import_session_sync(cdp_url: str, cookies: list[dict], handle: str | None = None) -> bool:
    return asyncio.run(import_session(cdp_url, cookies, handle))
