"""What the agent has learned, written down in plain words after every cycle and whenever the
session running it notices something. One markdown entry per cycle: what the source videos
showed (measured, not guessed), what the picker leaned on, how our posts did against the market,
and what changed since the last cycle. Served by the API as JSON and as one learnings.md."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

from .store import Store

SCHEMA = """CREATE TABLE IF NOT EXISTS learnings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at INTEGER,
  niche TEXT,
  product TEXT,
  kind TEXT,
  title TEXT,
  body TEXT,
  facts TEXT
)"""

CYCLE = "cycle"
NOTE = "note"
RULE = "rule"  # a standing do/don't the writer and the video prompt must follow

MIGRATIONS = ["ALTER TABLE renders ADD COLUMN hold_reason TEXT"]


def migrate(store: Store) -> None:
    import sqlite3

    with store.conn() as c:
        c.execute(SCHEMA)
        for m in MIGRATIONS:
            try:
                c.execute(m)
            except sqlite3.OperationalError:
                pass


def add_rule(store: Store, niche: str, product: str, text: str) -> int:
    """A standing rule in plain words ("the TV must show our game for the whole clip"). Rules go
    into every script prompt and every video prompt from now on; notes are what happened once."""
    return add(store, niche, product, text.strip().split("\n")[0][:80], text, kind=RULE)


def rules(store: Store, niche: str | None = None) -> list[str]:
    """Standing rules, oldest first, so the writer reads them in the order they were learned."""
    return [
        e["body"].strip() for e in reversed(entries(store, niche, limit=500)) if e["kind"] == RULE
    ]


def rules_text(store: Store, niche: str | None = None) -> str:
    rs = rules(store, niche)
    if not rs:
        return ""
    return "Standing rules from review (always apply):\n" + "\n".join(f"- {r}" for r in rs)


def hold(store: Store, script_id: int, reason: str) -> int:
    """Keep a clip out of the walkthrough and off the ready-to-post list, with the reason shown
    on Clips. Returns how many renders it touched."""
    migrate(store)
    with store.conn() as c:
        return c.execute(
            "UPDATE renders SET hold_reason=? WHERE script_id=?",
            (reason.strip() or "on hold", script_id),
        ).rowcount


def release(store: Store, script_id: int) -> int:
    migrate(store)
    with store.conn() as c:
        return c.execute(
            "UPDATE renders SET hold_reason=NULL WHERE script_id=?", (script_id,)
        ).rowcount


def add(
    store: Store,
    niche: str,
    product: str,
    title: str,
    body: str,
    kind: str = NOTE,
    facts: dict | None = None,
) -> int:
    migrate(store)
    return store.insert(
        "learnings",
        {
            "created_at": int(time.time()),
            "niche": niche,
            "product": product,
            "kind": kind,
            "title": title.strip(),
            "body": body.strip(),
            "facts": json.dumps(facts or {}),
        },
    )


def entries(store: Store, niche: str | None = None, limit: int = 50) -> list[dict]:
    migrate(store)
    where, args = ("WHERE niche=?", (niche,)) if niche else ("", ())
    rows = store.rows(
        f"SELECT * FROM learnings {where} ORDER BY created_at DESC, id DESC LIMIT ?",
        (*args, limit),
    )
    for r in rows:
        r["facts"] = json.loads(r.get("facts") or "{}")
    return rows


def document(store: Store, niche: str | None = None) -> str:
    """Everything learned, newest first, as one markdown file."""
    out = ["# Learnings" + (f": {niche}" if niche else ""), ""]
    for e in entries(store, niche, limit=500):
        day = datetime.fromtimestamp(e["created_at"], UTC).strftime("%Y-%m-%d %H:%M UTC")
        out += [f"## {e['title']}", "", f"_{day}, {e['kind']}, {e['niche']}_", "", e["body"], ""]
    if len(out) == 2:
        out.append("Nothing yet. The first cycle writes the first entry.")
    return "\n".join(out)


def _latest_format(store: Store, niche: str) -> dict | None:
    from .research.format import FORMAT_KIND

    for r in store.rows(
        "SELECT payload FROM concepts WHERE niche=? ORDER BY created_at DESC, id DESC LIMIT 50",
        (niche,),
    ):
        p = json.loads(r["payload"] or "{}")
        if p.get("kind") == FORMAT_KIND:
            return p
    return None


def _speech_text(s: dict) -> str:
    sp = s.get("speech")
    if not sp or (isinstance(sp, str) and "no speech" in sp):
        return "no speech, music only"
    if isinstance(sp, dict):
        words = sp.get("words") or sp.get("text") or ""
        if isinstance(words, list):
            words = " ".join(w.get("word", w) if isinstance(w, dict) else str(w) for w in words)
        return f'spoken: "{str(words)[:80]}"' if words else "no speech, music only"
    return f'spoken: "{str(sp)[:80]}"'


def _fmt_views(v) -> str:
    v = v or 0
    return f"{v / 1e6:.1f}M" if v >= 1e6 else f"{v / 1e3:.0f}k" if v >= 1e3 else str(v)


def _lift(p: dict) -> float | None:
    """The lift the picker learns from: age-matched when a reference curve exists, else the
    account's usual (72h first, then now)."""
    if p.get("lift_matched") is not None:
        return p["lift_matched"]
    return p["lift_72h"] if p["lift_72h"] is not None else p["lift_now"]


TRAIT_TABLES = {
    "hooks": "Hook type",
    "styles": "Visual style",
    "pacing": "Pacing (cuts per 10s)",
    "sound": "Sound",
    "product_early": "Product on screen by 5s",
}
_TRAIT_COLUMN = {
    "hooks": "hook_type",
    "styles": "visual_style",
    "pacing": "pacing_bucket",
    "sound": "music_role",
    "product_early": "product_on_screen_by_5s",
}


def _trait_value(v) -> str:
    return {"True": "yes", "False": "no"}.get(str(v), str(v).replace("_", " "))


def write_cycle(store: Store, niche: str, product: str, stages: list[dict] | None = None) -> int:
    """Compose this cycle's entry from the db and store it. Deterministic: every statement comes
    from a stored measurement or score, so the file is a record, not a guess."""
    from .compare import compare
    from .own import own_posts
    from .policy import concept_scores, pick_shares
    from .scoreboard import build

    facts: dict = {}
    lines: list[str] = []
    prev = next((e for e in entries(store, niche) if e["kind"] == CYCLE), None)
    pf = prev["facts"] if prev else {}

    fmt = _latest_format(store, niche)
    lines += ["### What the source videos showed", ""]
    if fmt:
        sheet = fmt.get("beat_sheet") or {}
        srcs = fmt.get("sources") or []
        facts["sources"] = [s["id"] for s in srcs]
        facts["playback"] = {str(s["id"]): s.get("playback") for s in srcs}
        facts["hook_delivery"] = sheet.get("hook_delivery")
        facts["sound"] = fmt.get("sound")
        lines.append(
            f"Watched {len(srcs)} videos about the product (the ones with the most views, any age):"
        )
        for s in srcs:
            motion = s.get("motion")
            pb = s.get("playback") or "speed not measured"
            if motion is not None:
                pb += f" (motion {motion:.1f})"
            lines.append(
                f"- [{s.get('author', '?')}, {_fmt_views(s.get('views'))} views]({s.get('url', '')}):"
                f" {pb}; {_speech_text(s)}; {s.get('duration') or '?'}s"
            )
        lines += [
            "",
            f"Format they share: **{fmt.get('name', '')}**. {sheet.get('summary', '')}",
            f"- Hook: {sheet.get('hook_delivery', '?')}, {sheet.get('hook_shot', '')}",
            f"- Pacing: {sheet.get('pacing', '?')}",
            f"- Text on screen: up to {sheet.get('on_screen_text_lines', '?')} lines of"
            f" {sheet.get('text_budget_words', '?')} words",
            f"- Talking: {sheet.get('talking', '?')}",
            f"- Sound: {fmt.get('sound') or 'no shared sound'}",
        ]
        if sheet.get("dont"):
            lines.append("- Never: " + "; ".join(sheet["dont"]))
    else:
        lines.append(
            "No videos about the product itself in the db yet, so scripts follow the niche's"
            " concepts instead of a cloned format."
        )

    sb = build(store, tags=store.niche_tags(niche) or None)
    facts["n_videos"] = len(sb["videos"])
    facts["n_scored"] = sb["n_scored"]
    facts["n_tagged"] = sb["n_tagged"]
    facts["curve"] = sb["curve"]
    facts["traits"] = {k: sb[k][:8] for k in TRAIT_TABLES}
    lines += ["", "### What the data says", ""]
    lines.append(
        f"{facts['n_videos']} {niche} videos tracked, {facts['n_scored']} scored (a day old, views"
        f" against {niche} videos of the same age and account size), {facts['n_tagged']} classified."
        " Mean lift per trait value is log10: +1 is 10x. n is videos with that trait and a score."
    )
    for key, label in TRAIT_TABLES.items():
        table = sb[key]
        if not table:
            continue
        lines += ["", f"{label}:", "", "| value | mean lift | n | win rate |", "|---|---|---|---|"]
        for t in table[:6]:
            lines.append(
                f"| {_trait_value(t[_TRAIT_COLUMN[key]])} | {t['mean_reward']:+.2f}"
                f" ± {t['stderr']:.2f} | {t['n']} | {round(t['win_rate'] * 100)}% |"
            )
    if not any(sb[k] for k in TRAIT_TABLES):
        lines.append("No trait has two scored videos yet, so no trait table.")

    lines += ["", "### What the picker leaned on", ""]
    cs = concept_scores(store, niche)
    if cs:
        top = cs[0]
        facts["top_concept"] = top["name"]
        facts["picks"] = [
            {"name": c["name"], "share": round(p, 3), "n": c["n"]}
            for c, p in zip(cs, pick_shares(cs), strict=False)
        ][:8]
        with_data = [c for c in cs if c["n"]]
        lines.append(
            f"{len(cs)} concepts in the niche, {len(with_data)} with results from our own posts."
            + (
                " Picks are still exploration on market signal; own-post results take over as they come in."
                if not with_data
                else " Own-post results now move the picks."
            )
        )
        lines += ["", "| concept | market prior | our result | our posts |", "|---|---|---|---|"]
        for c in cs[:6]:
            obs = "" if c["mean_reward"] is None else f"{c['mean_reward']:+.2f}"
            lines.append(f"| {c['name'][:50]} | {c['prior']:.2f} | {obs} | {c['n']} |")
    else:
        lines.append("No concepts yet.")

    posts = own_posts(store)
    facts["own_posts"] = len(posts)
    facts["own"] = [
        {
            "url": p["url"],
            "concept": p["concept"],
            "age_h": p["age_h"],
            "views": p["views_now"],
            "lift": _lift(p),
            "engagement_per_1k": p.get("engagement_per_1k"),
        }
        for p in posts[:12]
    ]
    lifts = [_lift(p) for p in posts if _lift(p) is not None]
    facts["own_mean_lift"] = round(sum(lifts) / len(lifts), 3) if lifts else None
    lines += ["", "### How our posts did", ""]
    if posts:
        lines += [
            "| post | account | age h | views | concept | lift vs typical at its age |",
            "|---|---|---|---|---|---|",
        ]
        for p in posts[:12]:
            lift = _lift(p)
            lines.append(
                f"| {p['url']} | {p['author']} | {p['age_h']} | {p['views_now'] or ''} |"
                f" {p['concept'] or 'unmatched'} | {'' if lift is None else f'{lift:+.2f}'} |"
            )
        lifted = [p for p in posts if _lift(p) is not None]
        if lifted:
            best = max(lifted, key=_lift)
            facts["best_own_concept"] = best["concept"]
            lines += ["", f"Best so far: {best['concept'] or 'unmatched'} ({best['url']})."]
    else:
        lines.append("Nothing posted from our account yet, so nothing measured on our side.")

    cmp = compare(store)
    told = [r for r in cmp if r.get("verdict") and "untried" not in str(r["verdict"])]
    lines += ["", "### Ours vs the market", ""]
    if told:
        lines += ["| trait | value | market | ours | read |", "|---|---|---|---|---|"]
        for r in told[:10]:
            m = "" if r["market"] is None else f"{r['market']:+.2f} (n={r['market_n']})"
            o = "" if r["ours"] is None else f"{r['ours']:+.2f} (n={r['ours_n']})"
            lines.append(f"| {r['trait']} | {str(r['value'])[:40]} | {m} | {o} | {r['verdict']} |")
    elif cmp:
        wins = [r for r in cmp if r["market"] is not None][:5]
        lines.append(
            "Market only so far. What beats the account's usual views in the niche: "
            + "; ".join(
                f"{r['trait']} {r['value']} ({r['market']:+.2f}, n={r['market_n']})" for r in wins
            )
            + ". All untried by us."
        )
    else:
        lines.append("Nothing scored on either side yet.")

    changes = []
    if pf:
        if pf.get("sources") != facts.get("sources"):
            changes.append("the set of source videos changed")
        for vid, label in (facts.get("playback") or {}).items():
            if vid in (pf.get("playback") or {}) and pf["playback"][vid] != label:
                changes.append(f"video {vid} now measures as {label} (was {pf['playback'][vid]})")
        if pf.get("hook_delivery") != facts.get("hook_delivery"):
            changes.append(
                f"hook delivery read as {facts.get('hook_delivery')} (was {pf.get('hook_delivery')})"
            )
        if pf.get("top_concept") != facts.get("top_concept"):
            changes.append(
                f"top concept is now {facts.get('top_concept')} (was {pf.get('top_concept')})"
            )
        if (facts.get("n_scored") or 0) != (pf.get("n_scored") or 0):
            changes.append(
                f"{facts.get('n_scored') or 0} research videos scored (was {pf.get('n_scored') or 0})"
            )
        for key, label in TRAIT_TABLES.items():
            now = (facts.get("traits") or {}).get(key) or []
            was = (pf.get("traits") or {}).get(key) or []
            if now and was and now[0][_TRAIT_COLUMN[key]] != was[0][_TRAIT_COLUMN[key]]:
                changes.append(
                    f"best {label.lower()} is now {_trait_value(now[0][_TRAIT_COLUMN[key]])}"
                    f" ({now[0]['mean_reward']:+.2f}, n={now[0]['n']}), was"
                    f" {_trait_value(was[0][_TRAIT_COLUMN[key]])} ({was[0]['mean_reward']:+.2f})"
                )
        if (
            facts.get("own_mean_lift") is not None
            and pf.get("own_mean_lift") is not None
            and abs(facts["own_mean_lift"] - pf["own_mean_lift"]) >= 0.05
        ):
            changes.append(
                f"our posts' mean lift is {facts['own_mean_lift']:+.2f}"
                f" (was {pf['own_mean_lift']:+.2f})"
            )
        if (facts.get("own_posts") or 0) > (pf.get("own_posts") or 0):
            changes.append(
                f"{facts['own_posts'] - pf.get('own_posts', 0)} new post(s) of ours measured"
            )
        if pf.get("best_own_concept") != facts.get("best_own_concept") and facts.get(
            "best_own_concept"
        ):
            changes.append(f"best own concept is now {facts['best_own_concept']}")
    lines += ["", "### Changed since last cycle", ""]
    if not pf:
        lines.append("First entry.")
    elif changes:
        lines += [f"- {c}" for c in changes]
    else:
        lines.append("Nothing measurable changed.")

    if stages:
        failed = [s["stage"] for s in stages if s["status"] == "failed"]
        skipped = [s["stage"] for s in stages if s["status"] == "skipped"]
        lines += ["", "### This run", ""]
        lines.append(
            ("All stages ok." if not failed else f"Failed: {', '.join(failed)}.")
            + (f" Skipped: {', '.join(skipped)}." if skipped else "")
        )

    day = datetime.now(UTC).strftime("%Y-%m-%d")
    return add(store, niche, product, f"Cycle {day}", "\n".join(lines), kind=CYCLE, facts=facts)
