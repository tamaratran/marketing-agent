"""Why did one of our posts underperform? Compare it with the reference videos it cloned.

The usual causes she named: the clip was not clean (artifacts, the game on the TV drifting), the
caption reads off, the sound is missing or wrong, the people or the game look fake, the product
shows up late. Each post-mortem is a learning entry with the evidence, and each fix becomes a rule
the script writer and the video prompt follow (`learnings.add_rule`), so the next batch avoids it."""

from __future__ import annotations

import base64
import json
import tempfile
import time
from pathlib import Path

from pydantic import BaseModel

from .config import settings
from .learnings import add, add_rule, entries, migrate
from .store import Store

KIND = "postmortem"
MIN_AGE_H = 24.0
THRESHOLD = -0.3  # log10 lift vs matched videos: below half of what videos like it get

CHECKLIST = (
    "clean clip (artifacts, warped hands, the game or TV screen changing into another game, "
    "text artifacts, low resolution)",
    "caption (reads like an ad or AI copy, does not match the clip, wrong or spammy hashtags)",
    "audio or sound (no trending sound, sound does not fit, silence where the sources talk)",
    "looks fake (AI faces, impossible physics, lighting, lip sync, repeated motions)",
    "product shown too late or unclear (the sources show the product and the body-as-controller "
    "idea in the first 2 seconds)",
    "hook delivery (the sources' hook is spoken, sweaty, first person; ours is text or flat)",
    "pacing (the sources speed up gameplay; ours plays real time, or the clip is too long or short)",
)

SYSTEM = """You judge why a short TikTok we made got fewer views than the reference videos it
cloned. You see our clip (frames every FRAME_SECONDS s, transcript, caption, sound) and the same
for each reference video, with their view counts. Name only causes you can see in the frames or
read in the text; do not guess at the algorithm, posting time or luck. For each cause give the
evidence (which second, which frame, which words) and one concrete fix the script writer or the
video prompt can apply next time. If our clip matches the references on every point, say so with
an empty causes list."""


class Cause(BaseModel):
    cause: str
    evidence: str
    fix: str


class Verdict(BaseModel):
    summary: str
    causes: list[Cause]


def done_ids(store: Store, niche: str | None = None) -> set[str]:
    return {
        (e.get("facts") or {}).get("video_id")
        for e in entries(store, niche, limit=500)
        if e["kind"] == KIND
    }


def candidates(
    store: Store,
    niche: str | None = None,
    min_age_h: float = MIN_AGE_H,
    threshold: float = THRESHOLD,
    again: bool = False,
) -> list[dict]:
    """Our posts old enough to judge, with a script, below the threshold, not yet examined."""
    from .own import own_posts

    now = time.time()
    done = set() if again else done_ids(store, niche)
    out = []
    for p in own_posts(store):
        if niche and p.get("niche") not in (None, niche):
            continue
        if not p.get("script_id") or p["id"] in done:
            continue
        if (now - (p.get("create_time") or now)) / 3600 < min_age_h:
            continue
        lift = p.get("lift_matched")
        if lift is None or lift >= threshold:
            continue
        out.append(p)
    return out


def sources_for(store: Store, post: dict, n: int = 3) -> list[dict]:
    """The reference videos this post's script cloned: the concept's examples, most viewed first."""
    from .policy import concept_examples

    ids: list[str] = []
    if post.get("concept_id"):
        rows = store.rows("SELECT video_ids FROM concepts WHERE id=?", (post["concept_id"],))
        if rows:
            ids = json.loads(rows[0]["video_ids"] or "[]")
    if not ids:
        from .learnings import _latest_format

        fmt = _latest_format(store, post.get("niche") or "") or {}
        ids = [str(s["id"]) for s in fmt.get("sources") or []]
    return concept_examples(store, ids, n)


def our_clip(store: Store, script_id: int) -> Path | None:
    rows = store.rows(
        "SELECT post_path, final_path, raw_path FROM renders WHERE script_id=? "
        "ORDER BY id DESC LIMIT 1",
        (script_id,),
    )
    for r in rows:
        for k in ("post_path", "final_path", "raw_path"):
            if r[k] and Path(r[k]).exists():
                return Path(r[k])
    return None


def _describe(video: Path | None, meta: dict, client, every_s: float, d: Path) -> list[dict]:
    from .classifier.classify import sample_frames, transcribe

    text = (
        f"{meta['label']}: {meta.get('views') or 0:,} views. Caption: {meta.get('desc') or ''}\n"
        f"Sound: {meta.get('music') or ''}. Duration: {meta.get('duration') or '?'}s."
    )
    content: list[dict] = []
    if video is None:
        content.append({"type": "input_text", "text": text + " (no video file; stats only)"})
        return content
    frames = sample_frames(video, every_s, 360, d / video.stem)
    transcript = transcribe(video, client, settings.transcribe_model)
    content.append(
        {
            "type": "input_text",
            "text": f"{text}\nTranscript: {transcript or '(none)'}\n{len(frames)} frames follow.",
        }
    )
    for f in frames:
        content.append(
            {
                "type": "input_image",
                "detail": "low",
                "image_url": "data:image/jpeg;base64," + base64.b64encode(f.read_bytes()).decode(),
            }
        )
    return content


def judge(
    store: Store, post: dict, model: str | None = None, client=None, every_s: float = 2.0
) -> Verdict:
    from openai import OpenAI

    client = client or OpenAI()
    model = model or settings.openai_model
    sources = sources_for(store, post)
    content: list[dict] = [
        {
            "type": "input_text",
            "text": "Checklist: " + "; ".join(CHECKLIST) + ".",
        }
    ]
    with tempfile.TemporaryDirectory() as d:
        ours = our_clip(store, post["script_id"])
        content += _describe(
            ours,
            {
                "label": "OUR CLIP",
                "views": post.get("views_now"),
                "desc": post.get("desc"),
                "music": post.get("music"),
                "duration": post.get("duration"),
            },
            client,
            every_s,
            Path(d),
        )
        for i, s in enumerate(sources, 1):
            path = settings.videos_dir / f"{s['id']}.mp4"
            content += _describe(
                path if path.exists() else None,
                {**s, "label": f"REFERENCE {i} @{s.get('author') or '?'}"},
                client,
                every_s,
                Path(d),
            )
        resp = client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": SYSTEM.replace("FRAME_SECONDS", str(every_s))},
                {"role": "user", "content": content},
            ],
            text_format=Verdict,
        )
    return resp.output_parsed


def record(store: Store, post: dict, verdict: Verdict, niche: str, product: str) -> int:
    """One learning entry per post, plus one rule per fix so prompts pick it up."""
    migrate(store)
    lift = post.get("lift_matched")
    title = f"Post-mortem: s{post['script_id']} at {lift:+.2f} vs videos like it"
    body = [verdict.summary.strip(), ""]
    rule_ids = []
    for c in verdict.causes:
        body.append(f"- **{c.cause}**: {c.evidence} Fix: {c.fix}")
        rule_ids.append(add_rule(store, niche, product, c.fix))
    if not verdict.causes:
        body.append("Matches the references on every checklist point; no fix from this post.")
    return add(
        store,
        niche,
        product,
        title,
        "\n".join(body),
        kind=KIND,
        facts={
            "video_id": post["id"],
            "url": post.get("url"),
            "script_id": post["script_id"],
            "lift_matched": lift,
            "views": post.get("views_now"),
            "causes": [c.model_dump() for c in verdict.causes],
            "rule_ids": rule_ids,
        },
    )


def run(
    store: Store,
    niche: str,
    product: str,
    model: str | None = None,
    client=None,
    again: bool = False,
    limit: int = 3,
) -> list[dict]:
    out = []
    for post in candidates(store, niche, again=again)[:limit]:
        verdict = judge(store, post, model, client)
        lid = record(store, post, verdict, niche, product)
        out.append(
            {
                "video_id": post["id"],
                "script_id": post["script_id"],
                "learning": lid,
                "causes": len(verdict.causes),
            }
        )
    return out
