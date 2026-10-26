"""Our own posts: the self-improving half of the loop.

Discovery reads each registered account's profile feed in a verified Chrome login. Historical
posts establish the baseline, not campaign rewards. Posts made after registration enter the
cohort, and caption matching connects them to scripts. Hashtag discovery is an explicit fallback,
never a silent substitute for a failed login. Nothing here publishes to TikTok.

`own_rewards` turns those posts into the bandit's reward: per concept, the mean lift of our posts
(log10 views minus the account's own baseline, at 72h when reached, else at the latest poll with
an age discount), so the picker learns from what we actually posted, not only from the market."""

from __future__ import annotations

import difflib
import json
import math
import os
import re
import time

from .cohort import snapshot_creator, views_at
from .scoreboard import (
    ENGAGEMENT_WEIGHT,
    MIN_AGE_H_FOR_OWN,
    curve_points,
    engagement_lift,
    engagement_per_1k,
    expected_log,
    fit_curve,
)
from .store import Store

MIGRATIONS = [
    "ALTER TABLE videos ADD COLUMN ours INTEGER DEFAULT 0",
    "ALTER TABLE videos ADD COLUMN script_id INTEGER",
    """CREATE TABLE IF NOT EXISTS own_accounts (
         handle TEXT PRIMARY KEY, campaign_tag TEXT, product TEXT, added_at INTEGER)""",
]
MIN_MATCH = 0.45
OWN_HISTORY_DAYS = 180  # older posts of ours say little about what the account gets today


def migrate(store: Store) -> None:
    with store.conn() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(videos)")}
        for sql in MIGRATIONS:
            if sql.startswith("ALTER") and sql.split("ADD COLUMN ")[1].split()[0] in cols:
                continue
            c.execute(sql)


def add_account(store: Store, handle: str, campaign_tag: str, product: str = "") -> None:
    from .research.tiktok_auth import normalize_handle

    migrate(store)
    with store.conn() as c:
        c.execute(
            """INSERT INTO own_accounts VALUES (?,?,?,?)
               ON CONFLICT(handle) DO UPDATE SET campaign_tag=excluded.campaign_tag,
                                                product=excluded.product""",
            (
                normalize_handle(handle),
                campaign_tag.lstrip("#").lower(),
                product,
                int(time.time()),
            ),
        )


POST_URL = re.compile(r"tiktok\.com/@([\w.\-]+)/video/(\d+)")


def add_post(store: Store, url: str, caption: str = "", niche: str | None = None) -> dict:
    """Register a post a person made from one of our accounts, by its TikTok link. Public stats
    come over plain HTTP; a post still under review is stored with the caption given so the script
    match happens now and the next cycle's re-poll fills in the views once it is public."""
    from .research.tiktok_browser import poll_public_stats

    migrate(store)
    m = POST_URL.search(url)
    try:
        row = poll_public_stats(url)
    except Exception:
        row = None
    if not row and not m:
        raise ValueError(
            "Need a tiktok.com/@handle/video/<id> link (short links need a public post)"
        )
    ours = {a["handle"]: a for a in accounts(store)}
    author = ((row or {}).get("author") or m.group(1)).lower()
    if author not in ours:
        raise ValueError(f"@{author} is not one of our accounts; register it with `mkt own add`")
    now = int(time.time())
    public = bool(row)
    if not row:
        row = {
            "id": m.group(2),
            "url": f"https://www.tiktok.com/@{author}/video/{m.group(2)}",
            "author": author,
            "followers": None,
            "create_time": now,
            "duration": None,
            "desc": caption,
            "music": "",
            "hashtags": re.findall(r"#(\w+)", caption),
        }
    row["source_tag"] = "profile"
    if caption and not row.get("desc"):
        row["desc"] = caption
    store.upsert_video(row)
    with store.conn() as c:
        c.execute("DELETE FROM observations WHERE video_id=? AND views IS NULL", (row["id"],))
    sid, score = match_script(
        store,
        caption or row.get("desc", ""),
        posted_at=row["create_time"],
        niche=niche,
        product=ours[author]["product"],
    )
    with store.conn() as c:
        c.execute(
            """UPDATE videos SET ours=1, script_id=COALESCE(?, script_id), niche=COALESCE(?, niche),
                      cohort_at=COALESCE(cohort_at, ?) WHERE id=?""",
            (sid, niche, now, row["id"]),
        )
    if not store.rows("SELECT 1 FROM creator_snapshots WHERE author=?", (author,)):
        snapshot_creator(store, author)
    return {
        "id": row["id"],
        "url": row["url"],
        "author": author,
        "script_id": sid,
        "match": score,
        "views": row.get("views"),
        "public": public,
    }


def accounts(store: Store) -> list[dict]:
    migrate(store)
    return store.rows("SELECT * FROM own_accounts ORDER BY added_at")


def match_script(
    store: Store,
    desc: str,
    days: int = 60,
    *,
    posted_at: int | None = None,
    niche: str | None = None,
    product: str = "",
) -> tuple[int | None, float]:
    """The script whose hook + captions read most like this caption, if close enough."""
    since = int(time.time()) - days * 86400
    best, best_r = None, 0.0
    for s in store.rows(
        """SELECT s.id, s.hook, s.payload FROM scripts s
           LEFT JOIN concepts c ON c.id=s.concept_id
           WHERE s.created_at>=? AND s.created_at<=?
             AND (? IS NULL OR c.niche=?) AND (?='' OR s.product=?)
           ORDER BY s.created_at DESC""",
        (since, posted_at or int(time.time()), niche, niche, product, product),
    ):
        caps = " ".join(json.loads(s["payload"] or "{}").get("captions") or [])
        text = f"{s['hook']} {caps}".lower()
        r = difflib.SequenceMatcher(None, (desc or "").lower(), text).ratio()
        r = max(
            r,
            difflib.SequenceMatcher(None, (desc or "").lower(), (s["hook"] or "").lower()).ratio(),
        )
        if r > best_r:
            best, best_r = s["id"], r
    return (best, round(best_r, 3)) if best_r >= MIN_MATCH else (None, round(best_r, 3))


def sync_own(
    store: Store,
    cdp_url: str,
    niche: str,
    niche_tags: list[str],
    scrolls: int = 4,
    source: str = "profile",
) -> dict:
    """Read recent profile posts; only posts since registration enter the campaign cohort."""
    from .research.tiktok_auth import ensure_login_sync
    from .research.tiktok_browser import profile_stats, scrape_hashtag_sync, scrape_profile_sync

    migrate(store)
    ours = {a["handle"]: a for a in accounts(store)}
    if not ours:
        return {"accounts": 0, "found": 0, "new": 0}
    rows = {}
    if source == "profile":
        ensure_login_sync(cdp_url, os.environ.get("TIKTOK_POST_HANDLE") or next(iter(ours)))
        for handle in ours:
            for r in scrape_profile_sync(handle, cdp_url, scrolls=scrolls):
                if (r.get("author") or "").lower() == handle:
                    rows[r["id"]] = r
    elif source == "hashtag":
        tags = sorted(
            {a["campaign_tag"] for a in ours.values() if a["campaign_tag"]} | set(niche_tags)
        )
        for tag in tags:
            for r in scrape_hashtag_sync(tag, cdp_url, scrolls=scrolls):
                if (r.get("author") or "").lower() in ours:
                    rows[r["id"]] = r
    else:
        raise ValueError("source must be profile or hashtag")
    new = historical = 0
    for r in rows.values():
        account = ours[r["author"].lower()]
        known = store.rows("SELECT ours FROM videos WHERE id=?", (r["id"],))
        store.upsert_video(r)
        if r["create_time"] < account["added_at"]:
            historical += 1
            continue
        if known and known[0]["ours"]:
            continue
        sid, _ = match_script(
            store,
            r.get("desc", ""),
            posted_at=r["create_time"],
            niche=niche,
            product=account["product"],
        )
        with store.conn() as c:
            c.execute(
                "UPDATE videos SET ours=1, script_id=?, niche=?, cohort_at=COALESCE(cohort_at, ?) WHERE id=?",
                (sid, niche, int(time.time()), r["id"]),
            )
        new += 1
    for handle in ours:
        baseline = store.rows(
            """SELECT v.id, v.followers, o.views FROM videos v
               JOIN observations o ON o.video_id=v.id
               WHERE lower(v.author)=? AND v.create_time<? AND v.ours=0
                 AND o.observed_at=(SELECT MAX(observed_at) FROM observations WHERE video_id=v.id)""",
            (handle, min(ours[handle]["added_at"], int(time.time()) - 72 * 3600)),
        )
        try:
            stats = profile_stats(handle)
        except Exception:  # noqa: BLE001 - baseline is best effort
            stats = None
        snapshot_creator(store, handle, posts=baseline, stats=stats)
    return {
        "accounts": len(ours),
        "source": source,
        "found": len(rows),
        "new": new,
        "historical": historical,
    }


def own_posts(store: Store) -> list[dict]:
    """Every post from our accounts with its script, concept, baseline and current lift.

    Two baselines per post. `lift_now`/`lift_72h` compare with the account's usual views (median
    over its posts, whatever their age), kept for display. `lift_matched` compares with what a
    niche video of the same age from an account of the same size typically has right now (the
    reference curve, see scoreboard.fit_curve), plus the account's own track record against that
    curve when it has MIN_FOR_OWN_BASELINE posts from the last OWN_HISTORY_DAYS. That is the
    number the picker learns from: a 3 hour old post is judged against 3 hour old videos."""
    migrate(store)
    rows = store.rows(
        """SELECT v.id, v.url, v.author, v.desc, v.create_time, v.duration, v.source_tag, v.niche,
                  v.followers, v.script_id, s.hook, s.concept_id, c.name concept
           FROM videos v LEFT JOIN scripts s ON s.id=v.script_id
           LEFT JOIN concepts c ON c.id=s.concept_id WHERE v.ours=1 ORDER BY v.create_time DESC"""
    )
    now = int(time.time())
    ref = store.latest(None, limit=500, group="reference")
    curves: dict[str | None, dict | None] = {}
    offsets: dict[str | None, dict[str, float]] = {}
    niche_rows: dict[str | None, list[dict]] = {}
    for v in rows:
        niche = v.get("niche")
        if niche not in curves:
            tags = store.niche_tags(niche) if niche else []
            niche_rows[niche] = [r for r in ref if r["source_tag"] in tags] if tags else ref
            curves[niche] = _niche_curve(store, ref, niche, now)
            offsets[niche] = _account_offsets(store, curves[niche], now) if curves[niche] else {}
        curve = curves[niche]
        obs = store.rows(
            "SELECT observed_at, views, shares, saves FROM observations WHERE video_id=? "
            "ORDER BY observed_at",
            (v["id"],),
        )
        curve_pts = [((o["observed_at"] - v["create_time"]) / 3600, o["views"]) for o in obs]
        snap = store.rows(
            "SELECT median_log_views, n_posts, followers FROM creator_snapshots WHERE author=? "
            "ORDER BY taken_at DESC LIMIT 1",
            (v["author"],),
        )
        base = (
            snap[0]["median_log_views"]
            if snap and snap[0]["median_log_views"] is not None
            else None
        )
        followers = v.get("followers") or (snap[0]["followers"] if snap else None)
        v["followers"] = followers
        v["age_h"] = round((now - v["create_time"]) / 3600, 1)
        v["views_now"] = obs[-1]["views"] if obs else None
        v["views_72h"] = views_at(curve_pts, 72)
        v["baseline_log"] = base
        v["lift_72h"] = (
            (math.log10(v["views_72h"]) - base) if v["views_72h"] and base is not None else None
        )
        latest = v["views_now"]
        v["lift_now"] = (math.log10(latest) - base) if latest and base is not None else None
        v["n_obs"] = len(obs)
        v["account_offset"] = offsets[niche].get(v["author"], 0.0)
        last = obs[-1] if obs else {}
        v["engagement_per_1k"] = round(engagement_per_1k(last), 2) if obs else None
        v["engagement_lift"] = (
            engagement_lift(
                niche_rows[niche],
                last.get("views") or 0,
                last.get("shares") or 0,
                last.get("saves") or 0,
            )
            if obs
            else None
        )
        if curve and obs and latest:
            age_obs = (obs[-1]["observed_at"] - v["create_time"]) / 3600
            exp = expected_log(curve, age_obs, followers) + v["account_offset"]
            v["expected_log"] = round(exp, 3)
            v["lift_matched"] = round(math.log10(latest) - exp, 3)
        else:
            v["expected_log"] = None
            v["lift_matched"] = None
    return rows


def _niche_curve(store: Store, ref: list[dict], niche: str | None, now: int) -> dict | None:
    """The reference curve for one niche (its hashtags' videos), or over every reference video
    when the niche alone has too few."""
    tags = store.niche_tags(niche) if niche else []
    own = [r for r in ref if r["source_tag"] in tags] if tags else ref
    return fit_curve(curve_points(own, now)) or fit_curve(curve_points(ref, now))


def _account_offsets(store: Store, curve: dict, now: int) -> dict[str, float]:
    """Per account, the median of how its recent posts (last OWN_HISTORY_DAYS) sit against the
    reference curve, once it has MIN_FOR_OWN_BASELINE of them. Its usual, age-matched."""
    from .scoreboard import MIN_FOR_OWN_BASELINE

    rows = store.latest(None, limit=500, group="ours")
    resid: dict[str, list[float]] = {}
    for r in rows:
        if not r.get("views") or not r.get("create_time"):
            continue
        if now - r["create_time"] > OWN_HISTORY_DAYS * 86400:
            continue
        age_h = ((r.get("observed_at") or now) - r["create_time"]) / 3600
        if age_h < MIN_AGE_H_FOR_OWN:
            continue
        exp = expected_log(curve, age_h, r.get("followers"))
        resid.setdefault(r["author"], []).append(math.log10(r["views"]) - exp)
    return {
        a: round(sorted(v)[len(v) // 2], 3)
        for a, v in resid.items()
        if len(v) >= MIN_FOR_OWN_BASELINE
    }


def own_post_rewards(store: Store) -> list[dict]:
    """One row per post of ours the picker may learn from: video_id, concept_id and the reward
    (age-matched view lift plus ENGAGEMENT_WEIGHT times the shares+saves lift, discounted by age
    so a 6h-old post counts about 30% of a 72h one). Posts
    under MIN_AGE_H_FOR_OWN are skipped as noise. Without a reference curve (nothing scraped yet)
    the lift over the account's usual views stands in."""
    out = []
    for p in own_posts(store):
        if p["age_h"] < MIN_AGE_H_FOR_OWN:
            continue
        weight = min(1.0, (p["age_h"] / 72) ** 0.5)
        if p["lift_matched"] is not None:
            eng = p.get("engagement_lift") or 0.0
            r = (p["lift_matched"] + ENGAGEMENT_WEIGHT * eng) * weight
        elif p["lift_72h"] is not None:
            r = p["lift_72h"]
        elif p["lift_now"] is not None:
            r = p["lift_now"] * weight
        else:
            continue
        out.append({"video_id": p["id"], "concept_id": p["concept_id"], "reward": round(r, 3)})
    return out


def own_rewards(store: Store) -> dict[int, dict]:
    """concept_id -> {mean_reward, n} over own_post_rewards, for posts matched to a concept."""
    agg: dict[int, list[float]] = {}
    for p in own_post_rewards(store):
        if p["concept_id"] is not None:
            agg.setdefault(p["concept_id"], []).append(p["reward"])
    return {cid: {"mean_reward": round(sum(v) / len(v), 3), "n": len(v)} for cid, v in agg.items()}
