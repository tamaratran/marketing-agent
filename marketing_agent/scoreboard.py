"""Scoreboard: turn raw view counts into a reward, rank hooks and concepts by it, flag stuck accounts.

Reward per video is log10(views + 1), winsorized at the 95th percentile so one viral hit does not
dominate, then expressed relative to the baseline for that account (median over its videos, or the
niche median when the account has fewer than MIN_FOR_OWN_BASELINE videos). A reward of +1 means the
video did 10x what that account usually does. Public TikTok exposes views, likes, comments, shares
and saves, not watch time, so completion is approximated by shares + saves per 1k views.
"""

import math
import statistics
from collections import defaultdict

from .store import Store

MIN_FOR_OWN_BASELINE = 3
WINSOR_PCT = 0.95
SHADOWBAN_MIN_POSTS = 3
SHADOWBAN_VIEW_CEILING = 1000
MIN_AGE_H_FOR_JUDGEMENT = 24


def _winsor(values: list[float], pct: float = WINSOR_PCT) -> float:
    if not values:
        return math.inf
    s = sorted(values)
    return s[max(0, min(len(s) - 1, math.ceil(len(s) * pct) - 1))]


def rewards(rows: list[dict], now: int | None = None) -> list[dict]:
    """Attach `log_views`, `baseline`, `reward` and `engagement_per_1k` to each row. Rows need
    views/author/create_time; videos younger than MIN_AGE_H_FOR_JUDGEMENT get reward=None."""
    import time

    now = now or int(time.time())
    logs = [math.log10((r.get("views") or 0) + 1) for r in rows]
    cap = _winsor(logs)
    by_author: dict[str, list[float]] = defaultdict(list)
    for r, lv in zip(rows, logs, strict=True):
        r["log_views"] = min(lv, cap)
        by_author[r.get("author") or ""].append(r["log_views"])
    niche_median = statistics.median(r["log_views"] for r in rows) if rows else 0.0
    out = []
    for r in rows:
        own = by_author[r.get("author") or ""]
        base = statistics.median(own) if len(own) >= MIN_FOR_OWN_BASELINE else niche_median
        age_h = (now - (r.get("create_time") or now)) / 3600
        views = r.get("views") or 0
        r["baseline"] = round(base, 3)
        r["reward"] = round(r["log_views"] - base, 3) if age_h >= MIN_AGE_H_FOR_JUDGEMENT else None
        r["engagement_per_1k"] = (
            round(((r.get("shares") or 0) + (r.get("saves") or 0)) / views * 1000, 2)
            if views
            else 0
        )
        out.append(r)
    return out


def rank_by(rows: list[dict], key: str, min_n: int = 2) -> list[dict]:
    """Mean reward per value of `key` (e.g. hook_type, concept), with n and a 1-sigma error."""
    groups: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r.get("reward") is None or not r.get(key):
            continue
        groups[str(r[key])].append(r["reward"])
    table = []
    for k, v in groups.items():
        if len(v) < min_n:
            continue
        sd = statistics.pstdev(v) if len(v) > 1 else 0.0
        table.append(
            {
                key: k,
                "n": len(v),
                "mean_reward": round(statistics.mean(v), 3),
                "stderr": round(sd / math.sqrt(len(v)), 3),
                "win_rate": round(sum(1 for x in v if x > 0) / len(v), 2),
            }
        )
    return sorted(table, key=lambda t: -t["mean_reward"])


def growth(store: Store, video_id: str) -> dict | None:
    """Views per hour between the last two observations; None with fewer than two."""
    obs = store.rows(
        "SELECT observed_at, views FROM observations WHERE video_id=? ORDER BY observed_at DESC LIMIT 2",
        (video_id,),
    )
    if len(obs) < 2:
        return None
    dt_h = max((obs[0]["observed_at"] - obs[1]["observed_at"]) / 3600, 1 / 60)
    return {"vph_recent": round((obs[0]["views"] - obs[1]["views"]) / dt_h, 1), "obs": len(obs)}


def shadowban_flags(rows: list[dict], now: int | None = None) -> list[dict]:
    """Accounts whose last SHADOWBAN_MIN_POSTS+ videos (older than a day) all sit under 1k views.
    Views stuck in the hundreds across every post is the usual symptom of a throttled account."""
    import time

    now = now or int(time.time())
    by_author: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if (now - (r.get("create_time") or now)) / 3600 >= MIN_AGE_H_FOR_JUDGEMENT:
            by_author[r.get("author") or ""].append(r)
    flags = []
    for a, vids in by_author.items():
        vids = sorted(vids, key=lambda r: -(r.get("create_time") or 0))[:5]
        if len(vids) < SHADOWBAN_MIN_POSTS:
            continue
        views = [v.get("views") or 0 for v in vids]
        if max(views) < SHADOWBAN_VIEW_CEILING:
            flags.append(
                {
                    "author": a,
                    "followers": vids[0].get("followers"),
                    "posts_checked": len(vids),
                    "max_views": max(views),
                    "median_views": int(statistics.median(views)),
                }
            )
    return sorted(flags, key=lambda f: f["max_views"])


def build(
    store: Store,
    tag: str | None = None,
    limit: int = 500,
    tags: list[str] | None = None,
    group: str | None = "reference",
) -> dict:
    """Scored videos, hook/concept/style tables and stuck accounts for one group of videos:
    "reference" (scraped for research, the default) or "ours" (our accounts and briefed
    creators). The two are never pooled: a stranger's viral hit says nothing about our accounts,
    and throttling only matters on accounts we post from. Hashtag `tags` apply to reference only;
    our posts are found by account, not hashtag."""
    rows = store.latest(tag, limit=limit, group=group)
    if tags and group != "ours":
        rows = [r for r in rows if r["source_tag"] in tags]
    tags = store.tags_for([r["id"] for r in rows])
    for r in rows:
        t = tags.get(r["id"], {}).get("tags", {})
        r["hook_type"] = t.get("hook_type")
        r["concept"] = t.get("concept")
        r["visual_style"] = t.get("visual_style")
        r["product_on_screen_by_5s"] = t.get("product_on_screen_by_5s")
    scored = rewards(rows)
    return {
        "videos": sorted(scored, key=lambda r: -(r["reward"] if r["reward"] is not None else -9)),
        "hooks": rank_by(scored, "hook_type"),
        "concepts": rank_by(scored, "concept"),
        "styles": rank_by(scored, "visual_style"),
        "stuck_accounts": shadowban_flags(scored),
        "n_scored": sum(1 for r in scored if r["reward"] is not None),
        "n_tagged": sum(1 for r in scored if r["hook_type"]),
    }
