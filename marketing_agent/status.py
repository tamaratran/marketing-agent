"""`mkt status`: the whole campaign in one read, for the chat agent and for people. Everything
comes from the live API (the same JSON the site reads), so a sandbox with no local db still sees
what the site shows. Field names are the API's, so the agent can `curl` an endpoint for detail.

The status is a dict (`--json`) or markdown (`render`): campaign, our posts with views and lift,
the latest batch of proposed scripts, clips with their post state, what the data says (best bets
plus the trait tables), the agent's notes and rules, and any run in flight."""

import os
import re
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

TRAIT_WORDS = {
    ("visual_style", "screen_recording"): "screen recordings",
    ("visual_style", "realistic_footage"): "real footage",
    ("visual_style", "ugc_selfie"): "selfie clips",
    ("visual_style", "talking_head"): "talking heads",
    ("hook_type", "text_on_screen"): "a text hook",
    ("hook_type", "pov"): "a POV hook",
    ("hook_type", "question"): "a question hook",
    ("hook_type", "bold_claim"): "a bold claim",
    ("hook_type", "other"): "no set hook",
    ("pacing_bucket", "slow"): "slow pacing",
    ("pacing_bucket", "medium"): "medium pacing",
    ("pacing_bucket", "fast"): "fast cuts",
    ("music_role", "background"): "background music",
    ("music_role", "trend_sound"): "a trending sound",
    ("music_role", "voiceover_only"): "voiceover only",
    ("music_role", "none"): "no sound",
    ("product_on_screen_by_5s", "True"): "the product on screen in 5 seconds",
}


def clip_check(clip: dict, graded: dict | None, win_lengths: list[float]) -> list[dict]:
    """The clip against the winners, one row per item (`ok` False is something to fix): the
    file spec, then the rubric differences, what hurt and what looks fake once the video model
    has graded it, then the quality issues its label found."""
    meta = clip.get("meta") or {}
    f = meta.get("file") or {}
    gen = meta.get("generation") or {}
    out = []
    w, h = f.get("width"), f.get("height")
    if w and h:
        out.append({"item": "Vertical 9:16", "ok": abs(w / h - 9 / 16) < 0.01, "ours": f"{w}x{h}"})
    elif gen.get("aspect_ratio"):
        out.append(
            {
                "item": "Vertical 9:16",
                "ok": gen["aspect_ratio"] == "9:16",
                "ours": gen["aspect_ratio"],
            }
        )
    sound = f.get("audio") if f else gen.get("audio")
    if sound is not None:
        out.append({"item": "Has sound", "ok": bool(sound), "ours": "yes" if sound else "no"})
    length = f.get("duration_s") or gen.get("duration_s")
    if length and len(win_lengths) >= 2:
        lo, hi = min(win_lengths), max(win_lengths)
        out.append(
            {
                "item": "Length like the winners",
                "ok": lo <= length <= hi,
                "ours": f"{length:g}s",
                "want": f"{lo:g} to {hi:g}s",
            }
        )
    if graded:
        for d in graded.get("differences") or []:
            out.append({"item": d["label"], "ok": False, "ours": d["ours"], "want": d["winners"]})
        grade = graded.get("grade") or {}
        out += [
            {"item": "Looks fake", "ok": False, "ours": x} for x in grade.get("looks_fake") or []
        ]
        out += [{"item": "Hurt", "ok": False, "ours": x} for x in grade.get("hurt") or []]
    tags = (clip.get("labels") or {}).get("tags") or {}
    out += [
        {"item": "Quality issue", "ok": False, "ours": q} for q in tags.get("quality_issues") or []
    ]
    return out


def _views(n) -> str:
    n = n or 0
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(int(n))


def _plain_name(name) -> str:
    """A concept name as it reads in a sentence: without the "Clone:" prefix."""
    return (name or "").split(":", 1)[-1].strip()


def _and(items: list[str]) -> str:
    items = [i for i in items if i]
    return ", ".join(items[:-1]) + (" and " if len(items) > 1 else "") + items[-1] if items else ""


def _video_id(url) -> str | None:
    """The TikTok video id at the end of a /video/<id> URL, for the embedded player."""
    m = re.search(r"/video/(\d+)", url or "")
    return m.group(1) if m else None


def _promo_format(campaign: dict, get: Get) -> dict | None:
    """The format to copy when campaign.toml names the TikToks that actually promote the
    product: their author, url and latest views (GET /videos/{id}), most viewed first."""
    product = campaign.get("product") or {}
    urls = product.get("promo_videos") or []
    if not urls:
        return None
    examples = []
    for url in urls:
        vid = _video_id(url)
        detail = (get(f"/videos/{vid}") if vid else None) or {}
        video = detail.get("video") or {}
        views = max((o.get("views") or 0 for o in detail.get("observations") or []), default=0)
        author = video.get("author") or (re.search(r"/@([^/]+)/", url or "") or [None, None])[1]
        examples.append({"id": vid, "author": author, "url": url, "views": views or None})
    examples.sort(key=lambda e: -(e.get("views") or 0))
    return {
        "id": None,
        "name": f"The videos that promote {product.get('name') or 'the product'}",
        "description": product.get("promo_format") or "",
        "examples": examples,
        "n_scripts": 0,
    }


def _story(
    facts: dict,
    min_n: int,
    concepts: list,
    batch: list,
    posts: list,
    rubric: dict | None = None,
    promo: dict | None = None,
) -> dict:
    """Three plain sentences a person reads first: what was scanned, what it says, what we make.
    Every number is read from the data; nothing here is written by a model.

    The winning format is the batch's concept with the most-viewed examples (its `early_score`),
    which is the product's own viral posts when a clone format is in the batch."""
    n_scored = facts.get("n_scored") or 0
    n_tagged = facts.get("n_tagged") or 0
    bets = [
        b
        for b in _best_bets(facts.get("traits") or {}, min_n)
        if (b.get("lift") or 0) > 0 and b.get("value") != "other"
    ]
    by_id = {c.get("id"): c for c in concepts or []}
    in_batch = {s.get("concept_id") for s in batch}
    pool = [by_id[i] for i in in_batch if i in by_id] or list(by_id.values())
    top = max(pool, key=lambda c: c.get("early_score") or 0, default=None)

    scanned = (
        f"Scanned {n_scored} videos in the niche, scored each against videos of the same age "
        f"and account size, and sorted {n_tagged} of them by trait."
        if n_scored
        else "No videos scanned yet."
    )

    learned_bits = []
    fmt = None
    if promo and promo.get("examples"):
        ex = promo["examples"][:3]
        views = _and([_views(e.get("views")) for e in ex if e.get("views")])
        learned_bits.append(
            f"The format that wins is {promo['name'][0].lower() + promo['name'][1:]}"
            + (f": the top ones have {views} views" if views else "")
            + "."
        )
        fmt = {**promo, "examples": ex}
    elif top:
        ex = sorted(top.get("examples") or [], key=lambda e: -(e.get("views") or 0))[:3]
        views = _and([_views(e.get("views")) for e in ex if e.get("views")])
        learned_bits.append(
            f"The format that wins is the {_plain_name(top.get('name'))}"
            + (f": its top videos have {views} views" if views else "")
            + "."
        )
        fmt = {
            "id": top.get("id"),
            "name": top.get("name"),
            "description": top.get("description"),
            "examples": [
                {"author": e.get("author"), "url": e.get("url"), "views": e.get("views")}
                for e in ex
            ],
            "n_scripts": sum(1 for s in batch if s.get("concept_id") == top.get("id")),
        }
    if bets:
        learned_bits.append(
            "Across the whole set, the traits that lift views are "
            + _and(
                [
                    f"{TRAIT_WORDS.get((b['trait'], b['value']), b['value'].replace('_', ' '))} "
                    f"({b['lift_text']}, {b['n']} videos)"
                    for b in bets[:4]
                ]
            )
            + "."
        )
    learned = " ".join(learned_bits) or "Not enough scored videos to say what wins yet."

    if batch:
        names = []
        for s in batch:
            if s.get("concept") and s["concept"] not in names:
                names.append(s["concept"])
        making = f"So we are making {len(batch)} script{'s' if len(batch) != 1 else ''}"
        if fmt and fmt["n_scripts"]:
            making += f", {fmt['n_scripts']} in the {_plain_name(fmt['name'])}"
            others = [_plain_name(n) for n in names if n != fmt["name"]]
            if others:
                making += f" and the rest in {_and(others)}"
        elif names:
            making += f" in {_and([_plain_name(n) for n in names])}"
        making += "."
    else:
        making = "No batch of scripts proposed yet."
    scored = [p for p in posts if p.get("lift_now") is not None]
    if posts:
        best = max(scored, key=lambda p: p["lift_now"], default=None)
        making += f" {len(posts)} posted so far"
        making += (
            f"; the best, s{best.get('script_id')}, does {pct(best['lift_now'])} vs videos like it."
            if best
            else "; none old enough to read yet."
        )

    return {
        "scanned": scanned,
        "learned": learned,
        "making": making,
        "format": fmt,
        **_rubric_story(rubric or {}, posts),
    }


def _rubric_story(rubric: dict, posts: list) -> dict:
    """What the winners share (`must_have`), each posted clip's differences from them (worst
    post first, then the unposted clips), and the candidate variables, from GET /rubric."""
    must = [m for m in rubric.get("must_have") or [] if m.get("agreed")]
    by_script = {p.get("script_id"): p for p in posts if p.get("script_id") is not None}
    diffs = []
    for r in rubric.get("ours") or []:
        p = by_script.get(r.get("script_id")) or {}
        diffs.append(
            {
                "script_id": r.get("script_id"),
                "hook": r.get("hook") or p.get("hook"),
                "posted": bool(p),
                "lift": p.get("lift_now"),
                "lift_text": pct(p.get("lift_now")) if p else "not posted",
                "views": p.get("views_now"),
                "differences": r.get("differences") or [],
                "hurt": (r.get("grade") or {}).get("hurt") or [],
                "looks_fake": (r.get("grade") or {}).get("looks_fake") or [],
            }
        )
    diffs.sort(
        key=lambda d: (
            not d["posted"],
            d["lift"] if d["lift"] is not None else 9,
            -len(d["differences"]),
        )
    )
    n_win = len(rubric.get("winners") or [])
    return {
        "must_have": must,
        "n_winners_graded": n_win,
        "differences": diffs,
        "candidates": rubric.get("candidates") or {"hurt": [], "helped": []},
    }


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
    concepts = get("/concepts") or []
    rubric = get("/rubric") or {}

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
    story = _story(facts, min_n, concepts, batch, posts, rubric, _promo_format(campaign, get))
    fmt = next((c for c in concepts if c.get("id") == (story.get("format") or {}).get("id")), None)
    win_lengths = [e["duration"] for e in (fmt or {}).get("examples") or [] if e.get("duration")]
    graded = {g.get("script_id"): g for g in (rubric or {}).get("ours") or []}
    for r in renders:
        r["check"] = clip_check(r, graded.get(r["script_id"]), win_lengths)
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
        "story": story,
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

    if st.get("story"):
        y = st["story"]
        out.append(f"\n{y['scanned']} {y['learned']} {y['making']}")
        if y.get("must_have"):
            out.append(
                f"\nWhat the {y.get('n_winners_graded')} top videos share: "
                + "; ".join(
                    f"{m['label'].lower()} {m['text']} ({round(m['share'] * 100)}%)"
                    for m in y["must_have"]
                )
                + "."
            )
        for d in y.get("differences") or []:
            gap = (
                ", ".join(
                    f"{x['label'].lower()} {x['ours']} (they: {x['winners']})"
                    for x in d["differences"]
                )
                or "matches the winners on every variable"
            )
            out.append(f"- s{d['script_id']} ({d['lift_text']}): {gap}")

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
