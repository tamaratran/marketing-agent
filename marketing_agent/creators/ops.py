"""Creator ops: brief kept scripts out to human creators, track who posts and who stops, and work
out what each one is owed per 1k views. Nothing here sends a message anywhere: briefs are drafted
to the store and printed; a human pastes them into Discord, Sideshift or a clipping site."""

import json
import re
import time
from datetime import UTC, datetime

from ..store import Store

TIMESTAMP_RE = re.compile(r"^\[?\d+:\d{2}\s*(-|to)\s*\d+:\d{2}\]?\s*")
STALL_DAYS = 7


def _tiktok_id(url: str) -> str:
    m = re.search(r"/video/(\d+)", url)
    return m.group(1) if m else url.rstrip("/").rsplit("/", 1)[-1]


def draft_brief(
    product: str,
    scripts: list[dict],
    rate_per_1k: float,
    cap_usd: float,
    deadline_days: int,
) -> str:
    """Plain-text brief a creator can act on without a call. Scripts are the kept ones only."""
    lines = [
        f"Paid TikTok brief: {product}",
        "",
        f"Pay: ${rate_per_1k:.2f} per 1,000 views, counted 7 days after posting, capped at ${cap_usd:.0f} per video.",
        f"Deadline: post within {deadline_days} days of accepting. Post from your own US account, no reposts.",
        "Rules: hook in the first 3 seconds, product on screen by second 5, 10-20 seconds total, your face and voice, no AI voiceover. Say it in your own words; the lines below are the shape, not a script to read.",
        "",
        "Pick one:",
    ]
    for i, s in enumerate(scripts, 1):
        lines.append(f"{i}. Hook: {s['hook']}")
        for ln in (s.get("captions") or [])[:5]:
            lines.append(f"   - {TIMESTAMP_RE.sub('', ln)}")
        lines.append("")
    lines += [
        "When it is up, reply with the link. Views are read from the public page, so nothing else is needed from you.",
    ]
    return "\n".join(lines)


def create_brief(
    store: Store,
    product: str,
    script_ids: list[int],
    rate_per_1k: float = 1.0,
    cap_usd: float = 200.0,
    deadline_days: int = 5,
) -> dict:
    qs = ",".join("?" * len(script_ids))
    rows = store.rows(f"SELECT * FROM scripts WHERE id IN ({qs})", tuple(script_ids))
    scripts = [{**json.loads(r["payload"]), "id": r["id"]} for r in rows]
    body = draft_brief(product, scripts, rate_per_1k, cap_usd, deadline_days)
    bid = store.insert(
        "briefs",
        {
            "created_at": int(time.time()),
            "product": product,
            "script_ids": json.dumps(script_ids),
            "rate_per_1k": rate_per_1k,
            "cap_usd": cap_usd,
            "deadline_days": deadline_days,
            "body": body,
            "status": "draft",
        },
    )
    return {"id": bid, "body": body, "scripts": scripts}


def add_creator(
    store: Store,
    handle: str,
    channel: str,
    rate_per_1k: float,
    followers: int | None = None,
    notes: str = "",
) -> None:
    with store.conn() as c:
        c.execute(
            """INSERT INTO creators (handle, platform, channel, rate_per_1k, followers, added_at, notes)
               VALUES (?, 'tiktok', ?, ?, ?, ?, ?)
               ON CONFLICT(handle) DO UPDATE SET channel=excluded.channel, rate_per_1k=excluded.rate_per_1k,
               followers=COALESCE(excluded.followers, creators.followers), notes=excluded.notes""",
            (handle.lstrip("@"), channel, rate_per_1k, followers, int(time.time()), notes),
        )


def record_post(
    store: Store,
    creator: str,
    url: str,
    brief_id: int | None = None,
    script_id: int | None = None,
    stats: dict | None = None,
) -> str:
    """Link a posted video to a creator (and brief/script). `stats` is a poll_public_stats row;
    when given it is stored so the scoreboard sees the post straight away."""
    vid = stats["id"] if stats else _tiktok_id(url)
    if stats:
        store.upsert_video(stats)
    with store.conn() as c:
        c.execute(
            """INSERT INTO posts (video_id, creator, brief_id, script_id, posted_at, url)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(video_id) DO UPDATE SET creator=excluded.creator, brief_id=excluded.brief_id,
               script_id=excluded.script_id""",
            (
                vid,
                creator.lstrip("@"),
                brief_id,
                script_id,
                (stats or {}).get("create_time") or int(time.time()),
                url,
            ),
        )
    return vid


def payouts(store: Store, min_age_days: int = 7) -> list[dict]:
    """What each post has earned: views/1000 * creator rate, capped by the brief. Only posts older
    than `min_age_days` count, so a creator is paid on settled numbers, not the first-day spike."""
    now = int(time.time())
    rows = store.rows(
        """SELECT p.video_id, p.creator, p.url, p.posted_at, c.rate_per_1k, b.cap_usd,
                  (SELECT views FROM observations o WHERE o.video_id=p.video_id ORDER BY observed_at DESC LIMIT 1) views,
                  (SELECT amount_usd FROM payouts pay WHERE pay.video_id=p.video_id AND paid_at IS NOT NULL ORDER BY computed_at DESC LIMIT 1) paid
           FROM posts p LEFT JOIN creators c ON c.handle=p.creator LEFT JOIN briefs b ON b.id=p.brief_id"""
    )
    out = []
    for r in rows:
        age_d = (now - (r["posted_at"] or now)) / 86400
        views = r["views"] or 0
        rate = r["rate_per_1k"] or 0
        owed = min(views / 1000 * rate, r["cap_usd"] or float("inf"))
        out.append(
            {
                "creator": r["creator"],
                "video_id": r["video_id"],
                "url": r["url"],
                "age_days": round(age_d, 1),
                "views": views,
                "rate_per_1k": rate,
                "owed_usd": round(owed, 2),
                "settled": age_d >= min_age_days,
                "paid_usd": r["paid"] or 0.0,
            }
        )
    return sorted(out, key=lambda x: -x["owed_usd"])


def creator_report(store: Store, stall_days: int = STALL_DAYS) -> list[dict]:
    """Per creator: posts, median views, last post, and whether they have gone quiet."""
    now = int(time.time())
    creators = store.rows("SELECT * FROM creators ORDER BY added_at")
    out = []
    for c in creators:
        posts = store.rows(
            """SELECT p.posted_at,
                      (SELECT views FROM observations o WHERE o.video_id=p.video_id ORDER BY observed_at DESC LIMIT 1) views
               FROM posts p WHERE p.creator=? ORDER BY posted_at DESC""",
            (c["handle"],),
        )
        views = sorted((p["views"] or 0) for p in posts)
        last = posts[0]["posted_at"] if posts else None
        since_d = (now - (last or c["added_at"])) / 86400
        status = "never posted" if not posts else ("stalled" if since_d >= stall_days else "active")
        out.append(
            {
                "handle": c["handle"],
                "channel": c["channel"],
                "rate_per_1k": c["rate_per_1k"],
                "posts": len(posts),
                "median_views": views[len(views) // 2] if views else 0,
                "last_post": datetime.fromtimestamp(last, UTC).date().isoformat() if last else "",
                "days_since": round(since_d, 1),
                "status": status,
            }
        )
    return out
