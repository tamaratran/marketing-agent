"""TikTok scraping through a real Chrome session (CDP). No login needed for hashtag pages
and public video pages. Direct HTTP downloads of the video file are blocked, so the file is
fetched from inside the page."""

import asyncio
import base64
import json
import re
import time
from pathlib import Path

from playwright.async_api import async_playwright

HASHTAG_RE = re.compile(r"#(\w+)")


def _row(it: dict, source_tag: str) -> dict:
    s = it.get("stats", {})
    author = it.get("author", {}).get("uniqueId")
    return {
        "id": it["id"],
        "url": f"https://www.tiktok.com/@{author}/video/{it['id']}",
        "author": author,
        "followers": it.get("authorStats", {}).get("followerCount"),
        "create_time": int(it["createTime"]),
        "duration": it.get("video", {}).get("duration"),
        "desc": it.get("desc", ""),
        "music": it.get("music", {}).get("title", ""),
        "sound_id": it.get("music", {}).get("id"),
        "hashtags": HASHTAG_RE.findall(it.get("desc", "")),
        "source_tag": source_tag,
        "views": s.get("playCount"),
        "likes": s.get("diggCount"),
        "comments": s.get("commentCount"),
        "shares": s.get("shareCount"),
        "saves": int(s.get("collectCount") or 0),
    }


async def scrape_hashtag(tag: str, cdp_url: str, scrolls: int = 3) -> list[dict]:
    """Return one row per video on tiktok.com/tag/<tag>, newest first."""
    return await _scrape_items(
        f"https://www.tiktok.com/tag/{tag}", "/api/challenge/item_list", tag, cdp_url, scrolls
    )


async def scrape_profile(author: str, cdp_url: str, scrolls: int = 1) -> list[dict]:
    """The author's recent posts (for their baseline), newest first."""
    return await _scrape_items(
        f"https://www.tiktok.com/@{author}", "/api/post/item_list", "profile", cdp_url, scrolls
    )


async def _scrape_items(
    url: str, api_path: str, source_tag: str, cdp_url: str, scrolls: int
) -> list[dict]:
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp_url)
        page = await browser.contexts[0].new_page()
        items: dict[str, dict] = {}

        async def on_response(resp):
            if api_path not in resp.url:
                return
            try:
                data = await resp.json()
            except Exception:
                return
            for it in data.get("itemList") or []:
                items[it["id"]] = it

        page.on("response", on_response)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception:
            pass
        await page.wait_for_timeout(6000)
        for _ in range(scrolls):
            await page.mouse.wheel(0, 4000)
            await page.wait_for_timeout(2500)
        await page.close()
    rows = [_row(it, source_tag) for it in items.values()]
    rows.sort(key=lambda r: -r["create_time"])
    return rows


async def fetch_video(url: str, out: Path, cdp_url: str) -> dict:
    """Download a public TikTok video to `out` and return its current metadata/stats."""
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp_url)
        page = await browser.contexts[0].new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_selector(
            "script#__UNIVERSAL_DATA_FOR_REHYDRATION__", state="attached", timeout=30000
        )
        data = await page.evaluate(
            "() => JSON.parse(document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__').textContent)"
        )
        item = data["__DEFAULT_SCOPE__"]["webapp.video-detail"]["itemInfo"]["itemStruct"]
        src = item["video"].get("playAddr") or item["video"].get("downloadAddr")
        b64 = await page.evaluate(
            """async (u) => { const r = await fetch(u, {credentials:'include'}); const buf = await r.arrayBuffer();
               let s=''; const bytes=new Uint8Array(buf);
               for (let i=0;i<bytes.length;i+=0x8000) s+=String.fromCharCode.apply(null, bytes.subarray(i,i+0x8000));
               return btoa(s); }""",
            src,
        )
        await page.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(base64.b64decode(b64))
    return _row(item, source_tag="poll")


def scrape_hashtag_sync(tag: str, cdp_url: str, scrolls: int = 3) -> list[dict]:
    return asyncio.run(scrape_hashtag(tag, cdp_url, scrolls))


def scrape_profile_sync(author: str, cdp_url: str, scrolls: int = 1) -> list[dict]:
    return asyncio.run(scrape_profile(author, cdp_url, scrolls))


def fetch_video_sync(url: str, out: Path, cdp_url: str) -> dict:
    return asyncio.run(fetch_video(url, out, cdp_url))


def poll_public_stats(url: str) -> dict | None:
    """Stats for any public video via plain HTTP (no browser). Used by the scoreboard."""
    import httpx

    r = httpx.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130 Safari/537.36"
        },
        follow_redirects=True,
        timeout=30,
    )
    m = re.search(
        r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">(.*?)</script>',
        r.text,
    )
    if not m:
        return None
    try:
        item = json.loads(m.group(1))["__DEFAULT_SCOPE__"]["webapp.video-detail"]["itemInfo"][
            "itemStruct"
        ]
    except KeyError:
        return None
    row = _row(item, source_tag="poll")
    row["observed_at"] = int(time.time())
    return row


def profile_stats(author: str) -> dict | None:
    """Public account totals from the profile page (plain HTTP): followers, video count, total
    likes. TikTok returns an empty body for the posts API outside a signed session, so this is
    the baseline we can get for any creator without logging in."""
    import httpx

    r = httpx.get(
        f"https://www.tiktok.com/@{author}",
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130 Safari/537.36"
        },
        follow_redirects=True,
        timeout=30,
    )
    m = re.search(
        r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">(.*?)</script>',
        r.text,
    )
    if not m:
        return None
    try:
        info = json.loads(m.group(1))["__DEFAULT_SCOPE__"]["webapp.user-detail"]["userInfo"]
    except KeyError:
        return None
    st = info.get("stats") or info.get("statsV2") or {}
    return {
        "followers": int(st.get("followerCount") or 0),
        "video_count": int(st.get("videoCount") or 0),
        "heart_count": int(st.get("heartCount") or 0),
        "verified": bool(info.get("user", {}).get("verified")),
    }
