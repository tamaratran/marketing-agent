"""Scoreboard: turn raw view counts into a reward, rank hooks and concepts by it, flag stuck accounts.

Reward per video is log10(views + 1), winsorized at the 95th percentile so one viral hit does not
dominate, then expressed relative to what is typical for a video of that age from an account of
that size in the niche: a curve log10(views) ~ log10(age) + log10(followers) fitted on the
reference videos (see fit_curve). When we have MIN_FOR_OWN_BASELINE or more videos from the same
creator, their track record against that curve is added, so the baseline is the creator's usual,
age-matched. A reward of +1 means the video did 10x what a video like it usually has by now.
Public TikTok exposes views, likes, comments, shares and saves, not watch time, so completion is
approximated by shares + saves per 1k views.
"""

import math
import statistics
from collections import defaultdict

from .store import Store

MIN_FOR_OWN_BASELINE = 3
ENGAGEMENT_WEIGHT = 0.5  # shares+saves per 1k views count half as much as views themselves
WINSOR_PCT = 0.95
SHADOWBAN_MIN_POSTS = 3
SHADOWBAN_VIEW_CEILING = 1000
MIN_AGE_H_FOR_JUDGEMENT = 24
MIN_AGE_H_FOR_OWN = 6  # our own posts: younger than this is noise, so they do not move the picker
MIN_CURVE_POINTS = 30
CURVE_MIN_AGE_H = 0.5
CURVE_MAX_AGE_H = 168  # views plateau after a week; older videos are judged as week-old ones


def _winsor(values: list[float], pct: float = WINSOR_PCT) -> float:
    if not values:
        return math.inf
    s = sorted(values)
    return s[max(0, min(len(s) - 1, math.ceil(len(s) * pct) - 1))]


def fit_curve(points: list[tuple[float, float, float]]) -> dict | None:
    """Typical views by age and account size: least squares for
    log10(views + 1) = a + b*log10(age_h) + c*log10(followers + 1) over (age_h, views, followers)
    points from reference videos. None with fewer than MIN_CURVE_POINTS points. `sd` is the
    spread of the residuals, so callers can say how unusual a video is."""
    from .analysis import _solve

    pts = [
        (
            math.log10(min(max(a, CURVE_MIN_AGE_H), CURVE_MAX_AGE_H)),
            math.log10((v or 0) + 1),
            math.log10((f or 0) + 1),
        )
        for a, v, f in points
        if v is not None
    ]
    if len(pts) < MIN_CURVE_POINTS:
        return None
    xs = [(1.0, la, lf) for la, _, lf in pts]
    ys = [lv for _, lv, _ in pts]
    xtx = [[sum(x[i] * x[j] for x in xs) for j in range(3)] for i in range(3)]
    xty = [sum(x[i] * y for x, y in zip(xs, ys, strict=True)) for i in range(3)]
    try:
        a, b, c = _solve(xtx, xty)
    except (ZeroDivisionError, ValueError):
        return None
    resid = [y - (a + b * x[1] + c * x[2]) for x, y in zip(xs, ys, strict=True)]
    sd = statistics.pstdev(resid) if len(resid) > 1 else 0.0
    return {
        "a": round(a, 4),
        "b": round(b, 4),
        "c": round(c, 4),
        "n": len(pts),
        "sd": round(sd, 3),
        "followers_fill": round(statistics.median(x[2] for x in xs), 3),
    }


def expected_log(curve: dict, age_h: float, followers: int | None) -> float:
    """log10 views a typical niche video has at `age_h` from an account with `followers`."""
    la = math.log10(min(max(age_h, CURVE_MIN_AGE_H), CURVE_MAX_AGE_H))
    lf = math.log10(followers + 1) if followers else curve["followers_fill"]
    return curve["a"] + curve["b"] * la + curve["c"] * lf


def curve_points(rows: list[dict], now: int | None = None) -> list[tuple[float, float, float]]:
    """(age at observation, views, followers) per row, for fit_curve."""
    import time

    now = now or int(time.time())
    out = []
    for r in rows:
        if not r.get("create_time") or r.get("views") is None:
            continue
        age_h = ((r.get("observed_at") or now) - r["create_time"]) / 3600
        if age_h <= 0:
            continue
        out.append((age_h, r["views"], r.get("followers")))
    return out


def reference_curve(rows: list[dict], now: int | None = None) -> dict | None:
    """The curve rewards() judges against: fitted on these rows with the same view cap."""
    import time

    now = now or int(time.time())
    cap = _winsor([math.log10((r.get("views") or 0) + 1) for r in rows])
    return fit_curve([(a, min(v, 10**cap - 1), f) for a, v, f in curve_points(rows, now)])


def engagement_per_1k(r: dict) -> float:
    """Shares + saves per 1k views: the closest public TikTok gets to 'people kept this'."""
    views = r.get("views") or 0
    return ((r.get("shares") or 0) + (r.get("saves") or 0)) / views * 1000 if views else 0.0


def engagement_lift(rows: list[dict], views: int, shares: int, saves: int) -> float | None:
    """log10(shares+saves per 1k + 1) of one video against the median of `rows` (the niche)."""
    if not views:
        return None
    logs = [math.log10(engagement_per_1k(r) + 1) for r in rows if (r.get("views") or 0) > 0]
    if not logs:
        return None
    mine = math.log10(engagement_per_1k({"views": views, "shares": shares, "saves": saves}) + 1)
    return round(mine - statistics.median(logs), 3)


def rewards(rows: list[dict], now: int | None = None) -> list[dict]:
    """Attach `log_views`, `expected`, `baseline`, `reward`, `engagement_per_1k`,
    `engagement_lift` (vs the niche median, log10) and `reward_total` (reward plus
    ENGAGEMENT_WEIGHT times the engagement lift) to each row.
    Rows need views/author/create_time (followers and observed_at help); videos younger than
    MIN_AGE_H_FOR_JUDGEMENT get reward=None. The baseline is the age- and size-matched
    expectation plus the creator's own track record when MIN_FOR_OWN_BASELINE of their videos
    are here; without enough videos for a curve it falls back to the niche median."""
    import time

    now = now or int(time.time())
    logs = [math.log10((r.get("views") or 0) + 1) for r in rows]
    cap = _winsor(logs)
    for r, lv in zip(rows, logs, strict=True):
        r["log_views"] = min(lv, cap)
    curve = fit_curve([(a, min(v, 10**cap - 1), f) for a, v, f in curve_points(rows, now)])
    niche_median = statistics.median(r["log_views"] for r in rows) if rows else 0.0
    for r in rows:
        age_obs = ((r.get("observed_at") or now) - (r.get("create_time") or now)) / 3600
        r["expected"] = (
            round(expected_log(curve, age_obs, r.get("followers")), 3) if curve else niche_median
        )
        r["residual"] = r["log_views"] - r["expected"]
    by_author: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_author[r.get("author") or ""].append(r)
    eng_logs = [math.log10(engagement_per_1k(r) + 1) for r in rows if (r.get("views") or 0) > 0]
    eng_median = statistics.median(eng_logs) if eng_logs else 0.0
    out = []
    for r in rows:
        others = [o["residual"] for o in by_author[r.get("author") or ""] if o is not r]
        offset = statistics.median(others) if len(others) + 1 >= MIN_FOR_OWN_BASELINE else 0.0
        base = r["expected"] + offset
        age_h = (now - (r.get("create_time") or now)) / 3600
        views = r.get("views") or 0
        r["creator_offset"] = round(offset, 3)
        r["baseline"] = round(base, 3)
        r["reward"] = round(r["log_views"] - base, 3) if age_h >= MIN_AGE_H_FOR_JUDGEMENT else None
        r["engagement_per_1k"] = round(engagement_per_1k(r), 2)
        r["engagement_lift"] = (
            round(math.log10(r["engagement_per_1k"] + 1) - eng_median, 3) if views else None
        )
        r["reward_total"] = (
            round(r["reward"] + ENGAGEMENT_WEIGHT * r["engagement_lift"], 3)
            if r["reward"] is not None and r["engagement_lift"] is not None
            else r["reward"]
        )
        out.append(r)
    for r in out:
        r.pop("residual", None)
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
    "reference" (scraped for research, the default) or "ours" (our registered
    accounts). The two are never pooled: a stranger's viral hit says nothing about our accounts,
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
        "curve": reference_curve(rows),
        "videos": sorted(scored, key=lambda r: -(r["reward"] if r["reward"] is not None else -9)),
        "hooks": rank_by(scored, "hook_type"),
        "concepts": rank_by(scored, "concept"),
        "styles": rank_by(scored, "visual_style"),
        "stuck_accounts": shadowban_flags(scored),
        "n_scored": sum(1 for r in scored if r["reward"] is not None),
        "n_tagged": sum(1 for r in scored if r["hook_type"]),
    }
