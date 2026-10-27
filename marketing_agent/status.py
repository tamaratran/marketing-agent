"""`mkt status`: the whole campaign in one read, for the chat agent and for people. Everything
comes from the live API (the same JSON the site reads), so a sandbox with no local db still sees
what the site shows. Field names are the API's, so the agent can `curl` an endpoint for detail.

The status is a dict (`--json`) or markdown (`render`): campaign, our posts with views and lift,
the latest batch of proposed scripts, clips with their post state, what the data says (best bets
plus the trait tables), the agent's notes and rules, and any run in flight."""

import os
import time
from collections.abc import Callable

Get = Callable[[str], object]

CLIPS_URL = os.environ.get("MKT_CLIPS_URL", "https://mkt-dashboard-eta.vercel.app/renders").rstrip(
    "/"
)
FRAMES_URL = os.environ.get("MKT_FRAMES_URL", "https://mkt-dashboard-eta.vercel.app/frames").rstrip(
    "/"
)
# Same rules as the site (web/app/clips/status.ts): a hand-off older than this with no post is
# stale; after MAX_POST_ATTEMPTS automatic hand-backs the API stops retrying.
POST_RETRY_AFTER_S = 3600
MAX_POST_ATTEMPTS = 4
BATCH_WINDOW_S = 20 * 60  # scripts written within 20 minutes of the newest are one batch
RUN_STALE_S = 3 * 3600


def pct(lift: float | None) -> str:
    """Log10 lift in words: "+90%", "-46%", "same", or "3.2x" past +200%."""
    if lift is None:
        return "no data"
    x = 10**lift
    if x >= 3:
        return f"{x:.1f}x"
    d = round((x - 1) * 100)
    return "same" if d == 0 else f"{d:+d}%"


def age(hours: float | None) -> str:
    if hours is None:
        return ""
    return f"{round(hours)}h" if hours < 48 else f"{round(hours / 24)}d"


def clip_status(r: dict, posted: bool, now: float) -> str:
    if posted:
        return "posted"
    if r.get("hold_reason"):
        return "on hold"
    if r.get("post_session_url"):
        stale = now - (r.get("post_requested_at") or 0) >= POST_RETRY_AFTER_S
        if not stale:
            return "posting"
        if (r.get("post_attempts") or 0) < MAX_POST_ATTEMPTS:
            return "waiting"
    return "ready" if r.get("post_path") else "rendered"


def post_status(p: dict) -> str:
    if p.get("lift_72h") is not None:
        return "scored"
    return "too early" if (p.get("age_h") or 0) < 72 else "awaiting 72h check"


def _best_bets(traits: dict, min_n: int) -> list[dict]:
    bets = []
    for key, col in TRAITS:
        rows = [r for r in traits.get(key) or [] if (r.get("n") or 0) >= min_n]
        if not rows:
            continue
        top = max(rows, key=lambda r: r.get("mean_reward") or 0)
        bets.append(
            {
                "trait": col,
                "value": str(top.get(col)),
                "lift": top.get("mean_reward"),
                "lift_text": pct(top.get("mean_reward")),
                "n": top.get("n"),
            }
        )
    return sorted(bets, key=lambda b: -(b["lift"] or 0))


TRAITS = [
    ("hooks", "hook_type"),
    ("styles", "visual_style"),
    ("pacing", "pacing_bucket"),
    ("sound", "music_role"),
    ("product_early", "product_on_screen_by_5s"),
]


def build(get: Get, now: float | None = None) -> dict:
    """Pull the campaign from the API (`get(path)` returns parsed JSON) into one status dict."""
    now = now or time.time()
    campaign = get("/campaign") or {}
    ours = get("/ours") or {}
    scripts = get("/scripts?days=14&limit=200") or []
    renders = get("/renders") or []
    runs = get("/runs?limit=30") or []
    learnings = get("/learnings?limit=100") or []
    findings = get("/findings") or {}

    posts = sorted(ours.get("posts") or [], key=lambda p: -(p.get("create_time") or 0))
    for p in posts:
        p["status"] = post_status(p)
        p["lift_now_text"] = pct(p.get("lift_now"))
        p["lift_72h_text"] = pct(p.get("lift_72h"))
    posted_by_script = {p["script_id"]: p for p in posts if p.get("script_id") is not None}

    rendered = {r["script_id"] for r in renders}
    for r in renders:
        p = posted_by_script.get(r["script_id"])
        r["status"] = clip_status(r, bool(p), now)
        r["post_url"] = p["url"] if p else None
        r["views_now"] = p.get("views_now") if p else None
        r["clip_url"] = f"{CLIPS_URL}/s{r['script_id']}.mp4"
        r["clean_url"] = f"{CLIPS_URL}/s{r['script_id']}_clean.mp4" if r.get("post_path") else None
        r["poster_url"] = f"{FRAMES_URL}/s{r['script_id']}.jpg"

    newest = max((s.get("created_at") or 0 for s in scripts), default=0)
    batch = [s for s in scripts if (s.get("created_at") or 0) >= newest - BATCH_WINDOW_S]
    batch.sort(
        key=lambda s: (
            -((s.get("why") or {}).get("expected_lift") or 0),
            -(s.get("demo_score") or 0),
            s.get("id") or 0,
        )
    )
    for s in batch:
        s["rendered"] = s["id"] in rendered
        s["expected_lift_text"] = pct((s.get("why") or {}).get("expected_lift"))

    cycles = sorted(
        (e for e in learnings if e.get("kind") == "cycle" and e.get("facts")),
        key=lambda e: e.get("created_at") or 0,
    )
    latest = cycles[-1] if cycles else None
    facts = (latest or {}).get("facts") or {}
    min_n = findings.get("min_n") or 20
    notes = [e for e in learnings if e.get("kind") != "cycle"]
    notes.sort(key=lambda e: -(e.get("created_at") or 0))

    running = next(
        (
            r
            for r in runs
            if not r.get("finished_at")
            and not (r.get("note") or "").startswith("post s")
            and now - (r.get("created_at") or 0) < RUN_STALE_S
        ),
        None,
    )
    posting = [
        r for r in runs if not r.get("finished_at") and (r.get("note") or "").startswith("post s")
    ]

    account = (campaign.get("account") or {}).get("handle") or next(
        (a.get("handle") for a in ours.get("accounts") or []), None
    )
    followers = next((p.get("followers") for p in posts if p.get("followers")), None)
    return {
        "as_of": int(now),
        "api": None,  # filled by the CLI with the URL it read from
        "campaign": campaign,
        "account": {"handle": account, "followers": followers},
        "posts": posts,
        "proposed_scripts": batch,
        "clips": renders,
        "learnings": {
            "as_of": (latest or {}).get("created_at"),
            "n_scored": facts.get("n_scored"),
            "n_tagged": facts.get("n_tagged"),
            "min_n": min_n,
            "best_bets": _best_bets(facts.get("traits") or {}, min_n),
            "traits": facts.get("traits") or {},
            "rules": [e for e in notes if e.get("kind") == "rule"],
            "notes": [e for e in notes if e.get("kind") != "rule"][:10],
        },
        "running": running,
        "posting": posting,
        "runs": runs[:5],
    }


def _when(ts) -> str:
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(ts)) if ts else "never"


def render(st: dict) -> str:
    """The same status as markdown a person (or the chat) reads top to bottom."""
    c = st["campaign"]
    acc = st["account"]
    out = []
    handle = f"@{acc['handle']}" if acc.get("handle") else "no account"
    fol = f", {acc['followers']} followers" if acc.get("followers") else ""
    out.append(f"# {(c.get('product') or {}).get('name') or 'Campaign'} on TikTok ({handle}{fol})")
    out.append(
        f"Niche {(c.get('niche') or {}).get('name') or '?'}; a cycle makes "
        f"{(c.get('cycle') or {}).get('clips') or '?'} clips at {(c.get('cycle') or {}).get('resolution') or '?'}. "
        f"As of {_when(st['as_of'])}."
    )
    if st.get("running"):
        r = st["running"]
        out.append(
            f"\nA run is going since {_when(r.get('created_at'))}: {r.get('note') or 'cycle'} {r.get('url') or ''}"
        )
    if st.get("posting"):
        out.append(
            "Posting now: "
            + ", ".join((r.get("note") or "").removeprefix("post ") for r in st["posting"])
        )

    out.append("\n## Our posts")
    if not st["posts"]:
        out.append("None yet.")
    for p in st["posts"]:
        views = (
            f"{p['views_now']:,} views"
            if p.get("views_now") is not None
            else "views not checked yet"
        )
        lift = (
            f"{p['lift_72h_text']} vs the account's usual at 72h"
            if p.get("lift_72h") is not None
            else f"{p['lift_now_text']} vs videos like it so far"
            if p.get("lift_now") is not None
            else p["status"]
        )
        sid = f"s{p['script_id']} " if p.get("script_id") is not None else ""
        out.append(
            f'- {sid}"{p.get("hook") or p.get("desc") or ""}": {views}, {age(p.get("age_h"))} old, {lift}. {p.get("url") or ""}'
        )

    out.append("\n## Clips")
    if not st["clips"]:
        out.append("None rendered yet.")
    for r in st["clips"]:
        bits = [r["status"]]
        if r.get("hold_reason"):
            bits.append(f"held: {r['hold_reason']}")
        if r.get("views_now") is not None:
            bits.append(f"{r['views_now']:,} views")
        if r.get("post_text"):
            bits.append("text: " + " / ".join(r["post_text"]))
        link = r.get("post_url") or r.get("clean_url") or r["clip_url"]
        out.append(f'- s{r["script_id"]} "{r.get("hook") or ""}": {"; ".join(bits)}. {link}')

    out.append("\n## Proposed next scripts")
    if not st["proposed_scripts"]:
        out.append("None yet; research writes the first batch.")
    for s in st["proposed_scripts"]:
        done = ", rendered" if s.get("rendered") else ""
        out.append(
            f'- s{s["id"]} "{s.get("hook") or ""}" ({s.get("concept") or "?"}, {s["expected_lift_text"]} expected{done})'
        )

    L = st["learnings"]
    out.append("\n## What the data says")
    if L.get("as_of"):
        out.append(
            f"As of {_when(L['as_of'])}: {L.get('n_scored') or 0} videos scored, {L.get('n_tagged') or 0} classified by trait; values under {L['min_n']} videos are not trusted."
        )
    if L["best_bets"]:
        out.append(
            "Best bets: "
            + "; ".join(
                f"{b['trait']} {b['value']} {b['lift_text']} ({b['n']} videos)"
                for b in L["best_bets"]
            )
        )
    for key, col in TRAITS:
        rows = sorted(L["traits"].get(key) or [], key=lambda r: -(r.get("mean_reward") or 0))
        if rows:
            out.append(
                f"- {col}: "
                + ", ".join(
                    f"{r.get(col)} {pct(r.get('mean_reward'))} ({r.get('n')})" for r in rows
                )
            )
    if L["rules"]:
        out.append("\n## Rules every script follows")
        out += [f"- {e.get('body') or e.get('title')}" for e in L["rules"]]
    if L["notes"]:
        out.append("\n## Notes")
        out += [f"- {_when(e.get('created_at'))}: {e.get('title')}" for e in L["notes"]]
    return "\n".join(out) + "\n"
