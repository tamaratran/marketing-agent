"""Measurement layer: watch fresh videos as a cohort so the loop learns from curves, not snapshots.

A video enters the cohort when the radar sees it younger than COHORT_MAX_AGE_H. From then on
`repoll` records its public stats every couple of hours for REPOLL_DAYS, every cohort video gets
classified (not just the top few), the author's other posts give a baseline, and `build_features`
turns all of that into one wide row per video at fixed ages (1h, 6h, 24h, 72h, 7d) that the
analysis reads."""

from __future__ import annotations

import json
import math
import statistics
import time

from .store import Store

COHORT_MAX_AGE_H = 6
REPOLL_DAYS = 8
AGES_H = (1, 6, 24, 72, 168)
MIN_BASELINE_POSTS = 3

MIGRATIONS = [
    "ALTER TABLE videos ADD COLUMN niche TEXT",
    "ALTER TABLE videos ADD COLUMN cohort_at INTEGER",
    "ALTER TABLE videos ADD COLUMN sound_id TEXT",
    """CREATE TABLE IF NOT EXISTS creator_snapshots (
         author TEXT, taken_at INTEGER, followers INTEGER, n_posts INTEGER,
         median_views REAL, median_log_views REAL, video_count INTEGER, heart_count INTEGER,
         PRIMARY KEY (author, taken_at))""",
    """CREATE TABLE IF NOT EXISTS features (
         video_id TEXT PRIMARY KEY, built_at INTEGER, niche TEXT, payload TEXT)""",
]


def migrate(store: Store) -> None:
    with store.conn() as c:
        for sql in MIGRATIONS:
            if sql.startswith("ALTER"):
                table, col = sql.split()[2], sql.split()[-2]
                if col in {r[1] for r in c.execute(f"PRAGMA table_info({table})")}:
                    continue
            c.execute(sql)


def enroll(store: Store, niche: str, rows: list[dict], now: int | None = None) -> list[dict]:
    """Mark scraped rows younger than COHORT_MAX_AGE_H as cohort members of the niche."""
    now = now or int(time.time())
    fresh = [r for r in rows if (now - r["create_time"]) / 3600 <= COHORT_MAX_AGE_H]
    with store.conn() as c:
        for r in fresh:
            c.execute(
                "UPDATE videos SET niche=?, cohort_at=COALESCE(cohort_at, ?), sound_id=? WHERE id=?",
                (niche, now, r.get("sound_id"), r["id"]),
            )
    return fresh


def cohort_videos(store: Store, max_age_days: float = REPOLL_DAYS, niche: str | None = None):
    since = int(time.time()) - int(max_age_days * 86400)
    sql = "SELECT * FROM videos WHERE cohort_at IS NOT NULL AND create_time>=?"
    args: list = [since]
    if niche:
        sql += " AND niche=?"
        args.append(niche)
    return store.rows(sql + " ORDER BY create_time DESC", tuple(args))


def repoll(store: Store, max_age_days: float = REPOLL_DAYS, niche: str | None = None) -> dict:
    """Record fresh public stats for every cohort video still inside the window (HTTP only)."""
    from .research.tiktok_browser import poll_public_stats

    ok = failed = 0
    for v in cohort_videos(store, max_age_days, niche):
        try:
            row = poll_public_stats(v["url"])
        except Exception:
            row = None
        if not row:
            failed += 1
            continue
        row["source_tag"] = v["source_tag"]
        store.upsert_video(row)
        ok += 1
    return {"polled": ok, "failed": failed}


def snapshot_creator(
    store: Store, author: str, posts: list[dict] | None = None, stats: dict | None = None
) -> dict:
    """Baseline for an account: median views of its other posts we know about, plus the public
    profile totals (followers, video count, total likes) when given."""
    stats = stats or {}
    if posts is None:
        posts = store.rows(
            """SELECT v.id, v.followers, o.views FROM videos v JOIN observations o ON o.video_id=v.id
               WHERE v.author=? AND o.observed_at=(SELECT MAX(observed_at) FROM observations
               WHERE video_id=v.id)""",
            (author,),
        )
    views = [p["views"] for p in posts if p.get("views")]
    snap = {
        "author": author,
        "taken_at": int(time.time()),
        "followers": stats.get("followers")
        or (max((p.get("followers") or 0) for p in posts) if posts else None),
        "n_posts": len(views),
        "video_count": stats.get("video_count"),
        "heart_count": stats.get("heart_count"),
        "median_views": statistics.median(views) if views else None,
        "median_log_views": statistics.median(math.log10(v) for v in views) if views else None,
    }
    store.insert("creator_snapshots", snap)
    return snap


def latest_snapshot(store: Store, author: str) -> dict | None:
    rows = store.rows(
        "SELECT * FROM creator_snapshots WHERE author=? ORDER BY taken_at DESC LIMIT 1", (author,)
    )
    return rows[0] if rows else None


def views_at(obs: list[tuple[float, float]], age_h: float) -> float | None:
    """Views at a fixed age from the observation curve: log-linear interpolation between the
    nearest observations, None when the video has not reached that age or we never saw it
    close enough (within 25% of the age) on at least one side."""
    pts = sorted((a, v) for a, v in obs if v is not None and a >= 0)
    if not pts or pts[-1][0] < age_h * 0.75:
        return None
    before = [p for p in pts if p[0] <= age_h]
    after = [p for p in pts if p[0] >= age_h]
    if before and after:
        (a0, v0), (a1, v1) = before[-1], after[0]
        if a1 == a0:
            return v0
        f = (age_h - a0) / (a1 - a0)
        return 10 ** (math.log10(max(v0, 1)) * (1 - f) + math.log10(max(v1, 1)) * f)
    a, v = after[0] if after else before[-1]
    if abs(a - age_h) <= age_h * 0.25:
        return v * age_h / a if a else v
    return None


def bucket(x, edges: list[float], labels: list[str]) -> str | None:
    if x is None:
        return None
    for e, lab in zip(edges, labels, strict=False):
        if x < e:
            return lab
    return labels[-1]


def video_features(store: Store, v: dict, now: int | None = None) -> dict:
    now = now or int(time.time())
    obs = store.rows(
        "SELECT observed_at, views FROM observations WHERE video_id=? ORDER BY observed_at",
        (v["id"],),
    )
    curve = [((o["observed_at"] - v["create_time"]) / 3600, o["views"]) for o in obs]
    tags = store.tags_for([v["id"]]).get(v["id"], {}).get("tags", {})
    snap = latest_snapshot(store, v["author"])
    base = snap["median_log_views"] if snap and snap["n_posts"] >= MIN_BASELINE_POSTS else None
    at = {f"views_{a}h": views_at(curve, a) for a in AGES_H}
    vph = {f"vph_{a}h": (at[f"views_{a}h"] / a if at[f"views_{a}h"] else None) for a in AGES_H}
    v72 = at["views_72h"]
    posted = time.gmtime(v["create_time"])
    return {
        "video_id": v["id"],
        "author": v["author"],
        "niche": v.get("niche") or v["source_tag"],
        "source_tag": v["source_tag"],
        "age_h": round((now - v["create_time"]) / 3600, 1),
        "n_obs": len(obs),
        **at,
        **vph,
        "growth_6_24": (
            math.log10(at["views_24h"] / at["views_6h"])
            if at["views_24h"] and at["views_6h"]
            else None
        ),
        "log_views_72h": math.log10(v72) if v72 else None,
        "creator_baseline_log": base,
        "lift_72h": (math.log10(v72) - base) if v72 and base is not None else None,
        "followers": v.get("followers"),
        "follower_bucket": bucket(
            v.get("followers"),
            [1e3, 1e4, 1e5, 1e6],
            ["<1k", "1k-10k", "10k-100k", "100k-1m", "1m+"],
        ),
        "duration_s": v.get("duration"),
        "duration_bucket": bucket(
            v.get("duration"), [10, 20, 40, 60], ["<10s", "10-20s", "20-40s", "40-60s", "60s+"]
        ),
        "posted_hour_utc": posted.tm_hour,
        "posted_hour_bucket": bucket(
            posted.tm_hour, [6, 12, 18], ["night", "morning", "afternoon", "evening"]
        ),
        "posted_weekday": posted.tm_wday,
        "sound": v.get("music"),
        "hashtags": json.loads(v.get("hashtags") or "[]"),
        "hook_type": tags.get("hook_type"),
        "visual_style": tags.get("visual_style"),
        "concept": tags.get("concept"),
        "product_on_screen_by_5s": tags.get("product_on_screen_by_5s"),
        "pacing_bucket": bucket(
            tags.get("pacing_cuts_per_10s"), [2, 4, 7], ["slow", "medium", "fast", "frantic"]
        ),
        "demo_score": tags.get("demo_score_1_5"),
        "tagged": bool(tags),
    }


def build_features(store: Store, niche: str | None = None) -> int:
    """One wide row per cohort video (any age; rows keep filling in as the curve grows)."""
    sql = "SELECT * FROM videos WHERE cohort_at IS NOT NULL"
    args: tuple = ()
    if niche:
        sql += " AND niche=?"
        args = (niche,)
    n = 0
    now = int(time.time())
    with store.conn() as c:
        for v in store.rows(sql, args):
            f = video_features(store, v, now)
            c.execute(
                "INSERT OR REPLACE INTO features (video_id, built_at, niche, payload) VALUES (?,?,?,?)",
                (v["id"], now, f["niche"], json.dumps(f)),
            )
            n += 1
    return n


def features(store: Store, niche: str | None = None) -> list[dict]:
    sql = "SELECT payload FROM features"
    args: tuple = ()
    if niche:
        sql += " WHERE niche=?"
        args = (niche,)
    return [json.loads(r["payload"]) for r in store.rows(sql, args)]
