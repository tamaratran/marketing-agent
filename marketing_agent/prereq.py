"""What must happen before a script is written, in this order: the video model grades the
winners and every clip of ours on the rubric, what it found goes into the learnings, and the
learnings are read back into the writer's prompt. `mkt scripts` and the cycle call
`before_scripts`; a batch is never written from a stale grade or from memory."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from . import learnings as L
from . import rubric as R
from .store import Store

NOTE_PREFIX = "Rubric before scripts"
BODY_LIMIT = 1500  # characters of each note the writer gets; rules always go in whole


class NotReady(RuntimeError):
    """The prerequisites did not hold; nothing was written."""


def grade(
    store: Store,
    cdp_url: str,
    videos_dir: Path,
    renders_dir: Path,
    winner_ids: list[str] | None,
    log=print,
) -> dict:
    """Grade whatever is not graded yet and build the comparison. Every named winner must have a
    grade; a clip of ours that fails is reported but does not stop the batch."""
    res = R.run(store, cdp_url, videos_dir, renders_dir, video_ids=winner_ids or None, log=log)
    rep = R.report(store, winner_ids=winner_ids or None)
    failed = "; ".join(res.get("failed") or [])
    if not rep["winners"]:
        raise NotReady(
            "no winner has a grade: "
            + (failed or "nothing to grade (are the promo videos in the db?)")
        )
    have = {str(w["video_id"]) for w in rep["winners"]}
    missing = [str(v) for v in (winner_ids or []) if str(v) not in have]
    if missing:
        raise NotReady(
            f"winners not graded: {', '.join(missing)}"
            + (f"; failures: {failed}" if failed else "")
        )
    return {"run": res, "report": rep}


def digest(rep: dict) -> str:
    """Same must-haves and same differences per clip means the same finding; no second note."""
    key = {
        "must": [(m["variable"], m["value"], m["agreed"]) for m in rep["must_have"]],
        "ours": sorted(
            (str(r["script_id"]), sorted(d["variable"] for d in r["differences"]))
            for r in rep["ours"]
        ),
    }
    return hashlib.sha1(json.dumps(key, sort_keys=True).encode()).hexdigest()[:12]


def note_body(rep: dict) -> str:
    n_win, n_ours = len(rep["winners"]), len(rep["ours"])
    out = [
        f"The video model watched {n_win} winner{'s' if n_win != 1 else ''} of the format and "
        f"{n_ours} clip{'s' if n_ours != 1 else ''} of ours and graded each on the same rubric."
    ]
    must = [m for m in rep["must_have"] if m["agreed"]]
    if must:
        out += ["", "What the winners share:"]
        out += [f"- {m['label']}: {m['text']} ({round(m['share'] * 100)}% of them)" for m in must]
    ours = [r for r in rep["ours"] if r["differences"]]
    if ours:
        out += ["", "Where our clips differ:"]
        for r in ours:
            d = "; ".join(
                f"{x['label']} {x['ours']} (winners {x['winners']})" for x in r["differences"]
            )
            hook = f' "{r["hook"]}"' if r.get("hook") else ""
            out.append(f"- s{r['script_id']}{hook}: {d}")
    elif rep["ours"]:
        out += ["", "Every clip of ours matches what the winners share."]
    hurt = rep["candidates"]["hurt"][:6]
    helped = rep["candidates"]["helped"][:6]
    if hurt:
        out += [
            "",
            "What the model says hurt our clips: " + "; ".join(c["text"] for c in hurt) + ".",
        ]
    if helped:
        out += [
            "",
            "What it says helped the winners: " + "; ".join(c["text"] for c in helped) + ".",
        ]
    return "\n".join(out)


def record(store: Store, niche: str, product: str, rep: dict) -> int | None:
    """Write the grading into the learnings, unless the latest rubric note already says this."""
    d = digest(rep)
    for e in L.entries(store, niche, limit=100):
        if e["facts"].get("rubric_digest") == d:
            return None
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    return L.add(
        store,
        niche,
        product,
        f"{NOTE_PREFIX}, {day}: what the winners share and where our clips differ",
        note_body(rep),
        kind=L.NOTE,
        facts={
            "rubric_digest": d,
            "rubric_version": rep.get("rubric_version"),
            "winners": len(rep["winners"]),
            "ours": len(rep["ours"]),
        },
    )


def brief(store: Store, niche: str | None, notes: int = 5) -> str:
    """The learnings as the writer reads them: every standing rule, then the newest notes."""
    parts = []
    rules = L.rules_text(store, niche)
    if rules:
        parts.append(rules)
    latest = [e for e in L.entries(store, niche, limit=100) if e["kind"] != L.RULE][:notes]
    if latest:
        parts.append(
            "Latest findings, newest first:\n\n"
            + "\n\n".join(
                f"### {e['title']}\n{e['body'][:BODY_LIMIT]}"
                + ("..." if len(e["body"]) > BODY_LIMIT else "")
                for e in latest
            )
        )
    return "\n\n".join(parts)


def before_scripts(
    store: Store,
    *,
    niche: str,
    product: str,
    winner_ids: list[str] | None,
    cdp_url: str,
    videos_dir: Path,
    renders_dir: Path,
    log=print,
) -> str:
    """Grade, write the learnings, read them back. Returns the text the writer must read; raises
    NotReady when a step did not hold."""
    g = grade(store, cdp_url, videos_dir, renders_dir, winner_ids, log=log)
    rep = g["report"]
    log(
        f"rubric: {g['run']['winners']} winners and {g['run']['ours']} clips newly graded; "
        f"{len(rep['winners'])} winners and {len(rep['ours'])} clips in the comparison"
    )
    added = record(store, niche, product, rep)
    log(
        "learnings: " + ("rubric note written" if added else "rubric unchanged since the last note")
    )
    text = brief(store, niche)
    if not text:
        raise NotReady("the learnings are empty after grading; nothing to write from")
    log(f"learnings: {len(text)} characters read into the writer's prompt")
    return text
