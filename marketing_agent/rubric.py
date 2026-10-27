"""Her rubric: the things in a video that decide whether it goes viral, graded the same way on
the proven winners and on our clips, so the gap between them is a list of named differences and
not a feeling. Content, the game on screen, captions, the person (how many, gender, build,
clothing, sweat), speech, how fast they move, the activity, the sound, the pacing, what looks
fake, and two open fields (what helped, what hurt) that feed the next version of the rubric.

Gemini watches the whole video with sound (classifier/gemini.py's route). One row per video in
the `rubric` table; `report()` turns the rows into the must-have list (what the winners share),
the differences per clip of ours, and the candidate variables from the open fields."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .classifier.gemini import ENDPOINT, INLINE_LIMIT, _post
from .store import Store

SCHEMA = """CREATE TABLE IF NOT EXISTS rubric (
  key TEXT PRIMARY KEY,
  kind TEXT,
  video_id TEXT,
  script_id INTEGER,
  model TEXT,
  graded_at INTEGER,
  payload TEXT
)"""

RUBRIC_VERSION = "r1"
WINNER = "winner"
OURS = "ours"
CLIPS_URL = os.environ.get("MKT_CLIPS_URL", "https://mkt-dashboard-eta.vercel.app/renders").rstrip(
    "/"
)

SYSTEM = """You grade short vertical TikTok videos for a marketing team. Some are the most-viewed
videos in a format; some are the team's own clips in that format. Grade every video the same way,
from what you see and hear, never from the caption alone. Be literal: name the game or app on any
screen and say whether it is visibly working; quote on-screen text exactly; describe clothing in
a few words. Text fields with nothing to say are an empty string, never the word None.
`helped` and `hurt` are the two or three concrete things in this video most likely to have
helped or hurt its views, each a short phrase about something visible or audible (not the
algorithm, posting time or luck). Return JSON matching the schema."""


class Grade(BaseModel):
    content: str = Field(description="What happens in the video, one line")
    product_on_screen: Literal["no", "yes_working", "yes_wrong", "yes_unclear"] = Field(
        description="Is a game or app on a screen, and is it visibly the right one and working"
    )
    screen_text: str = Field(description="The game or app on the screen, named, or empty")
    captions: Literal["none", "readable", "typos", "covering_subject"] = Field(
        description="On-screen captions: none, readable, with typos or broken glyphs, or covering the subject"
    )
    caption_text: str = Field(description="The on-screen caption text, quoted exactly")
    people: Literal["none", "one", "two_or_more"]
    gender: Literal["none", "woman", "man", "mixed"]
    build: Literal["none", "slim", "average", "athletic", "heavy"]
    clothing: str = Field(description="What the person wears, a few words")
    sweat: Literal["none", "some", "a_lot"] = Field(description="How sweaty the person looks")
    speech: Literal["none", "a_few_words", "talks"]
    speech_text: str = Field(description="What is said out loud, quoted, or empty")
    movement: Literal["still", "slow", "moderate", "fast"] = Field(
        description="How fast the person moves"
    )
    activity: str = Field(description="The exercise, dance or activity, a few words")
    sound: Literal["none", "music", "trend_sound", "voice_only", "music_and_voice"]
    sound_fits: bool = Field(description="Does the sound fit what is on screen")
    pacing: Literal["one_shot", "few_cuts", "many_cuts"]
    looks_fake: list[str] = Field(description="Anything that looks AI-made or wrong, each a phrase")
    helped: list[str]
    hurt: list[str]


# The variables compared between the winners and our clips, in the order the page shows them.
VARIABLES = [
    ("product_on_screen", "Game on screen"),
    ("captions", "Captions"),
    ("people", "People"),
    ("gender", "Gender"),
    ("build", "Build"),
    ("sweat", "Sweat"),
    ("speech", "Speech"),
    ("movement", "Movement"),
    ("sound", "Sound"),
    ("sound_fits", "Sound fits"),
    ("pacing", "Pacing"),
]
TEXT_FIELDS = {k for k, f in Grade.model_fields.items() if f.annotation is str}
WORDS = {
    "yes_working": "yes, working",
    "yes_wrong": "yes, the wrong one",
    "yes_unclear": "yes, unclear",
    "covering_subject": "covering the subject",
    "two_or_more": "two or more",
    "a_lot": "a lot",
    "a_few_words": "a few words",
    "trend_sound": "a trending sound",
    "voice_only": "voice only",
    "music_and_voice": "music and voice",
    "one_shot": "one shot",
    "few_cuts": "a few cuts",
    "many_cuts": "many cuts",
    "True": "yes",
    "False": "no",
}


def word(value) -> str:
    s = str(value)
    return WORDS.get(s, s.replace("_", " "))


def migrate(store: Store) -> None:
    with store.conn() as c:
        c.execute(SCHEMA)


def _context(meta: dict) -> str:
    bits = []
    if meta.get("label"):
        bits.append(meta["label"])
    if meta.get("views"):
        bits.append(f"{meta['views']} views")
    if meta.get("desc"):
        bits.append(f"caption: {str(meta['desc'])[:300]}")
    if meta.get("music"):
        bits.append(f"sound: {meta['music']}")
    return "Post context: " + "; ".join(bits) if bits else "No post context."


def grade_video(
    video: Path,
    meta: dict,
    model: str | None = None,
    api_key: str | None = None,
    post=_post,
    timeout: float = 300,
) -> dict:
    """{"grade": Grade dict, "run": metadata}; the whole file goes to Gemini with its sound."""
    model = model or os.environ.get("MKT_VIDEO_LABEL_MODEL", "gemini-flash-latest")
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    data = video.read_bytes()
    if len(data) > INLINE_LIMIT:
        raise RuntimeError(f"{video.name} is {len(data) // 1_000_000} MB, over the inline limit")
    import base64

    t0 = time.time()
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [
            {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "video/mp4",
                            "data": base64.b64encode(data).decode(),
                        }
                    },
                    {"text": _context(meta)},
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": Grade.model_json_schema(),
            "temperature": 0.2,
        },
    }
    resp = post(ENDPOINT.format(model=model) + f"?key={api_key}", body, timeout)
    raw = json.loads(resp["candidates"][0]["content"]["parts"][0]["text"])
    for k in TEXT_FIELDS:
        if isinstance(raw.get(k), str) and raw[k].strip().lower() in {"none", "null", "n/a"}:
            raw[k] = ""
    grade = Grade.model_validate(raw)
    usage = resp.get("usageMetadata") or {}
    return {
        "grade": grade.model_dump(),
        "run": {
            "model": model,
            "rubric_version": RUBRIC_VERSION,
            "latency_s": round(time.time() - t0, 1),
            "input_tokens": usage.get("promptTokenCount"),
            "output_tokens": usage.get("candidatesTokenCount"),
        },
    }


def save(store: Store, kind: str, payload: dict, video_id: str | None = None, script_id=None):
    migrate(store)
    key = f"v:{video_id}" if kind == WINNER else f"s:{script_id}"
    with store.conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO rubric VALUES (?,?,?,?,?,?,?)",
            (
                key,
                kind,
                video_id,
                script_id,
                (payload.get("run") or {}).get("model"),
                int(time.time()),
                json.dumps(payload),
            ),
        )


def grades(store: Store) -> list[dict]:
    migrate(store)
    out = []
    for r in store.rows("SELECT * FROM rubric ORDER BY graded_at"):
        p = json.loads(r.pop("payload") or "{}")
        r["grade"] = p.get("grade") or {}
        r["run"] = p.get("run") or {}
        out.append(r)
    return out


def winning_concept(store: Store, days: int = 14) -> dict | None:
    """The format we are going after: among the concepts of the latest scripts, the one with the
    most-viewed examples (`early_score`); failing that, the top concept overall."""
    since = int(time.time()) - days * 86400
    ids = {
        r["concept_id"]
        for r in store.rows("SELECT DISTINCT concept_id FROM scripts WHERE created_at>=?", (since,))
        if r["concept_id"] is not None
    }
    rows = store.rows("SELECT * FROM concepts ORDER BY early_score DESC")
    pool = [r for r in rows if r["id"] in ids] or rows
    return pool[0] if pool else None


def winners(store: Store, concept: dict | None, n: int = 5) -> list[dict]:
    """The concept's example videos with what we know about them, most viewed first."""
    if not concept:
        return []
    ids = json.loads(concept.get("video_ids") or "[]")
    out = []
    for vid in ids:
        rows = store.rows("SELECT * FROM videos WHERE id=?", (str(vid),))
        if not rows:
            continue
        v = rows[0]
        obs = store.rows(
            "SELECT views FROM observations WHERE video_id=? ORDER BY observed_at DESC LIMIT 1",
            (str(vid),),
        )
        v["views"] = obs[0]["views"] if obs else None
        out.append(v)
    out.sort(key=lambda v: -(v.get("views") or 0))
    return out[:n]


def our_clips(store: Store) -> list[dict]:
    return store.rows(
        "SELECT r.script_id, r.post_path, r.final_path, r.raw_path, s.hook "
        "FROM renders r JOIN scripts s ON s.id=r.script_id "
        "WHERE r.id IN (SELECT MAX(id) FROM renders GROUP BY script_id) ORDER BY r.script_id"
    )


def _our_file(clip: dict, out_dir: Path) -> Path:
    for k in ("post_path", "final_path", "raw_path"):
        if clip.get(k) and Path(clip[k]).exists():
            return Path(clip[k])
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"s{clip['script_id']}_rubric.mp4"
    if target.exists():
        return target
    last = None
    for name in (f"s{clip['script_id']}_clean.mp4", f"s{clip['script_id']}.mp4"):
        try:
            urllib.request.urlretrieve(f"{CLIPS_URL}/{name}", target)
            return target
        except Exception as e:  # noqa: BLE001 - try the other name
            last = e
    raise RuntimeError(f"no file for s{clip['script_id']}: {last}")


def run(
    store: Store,
    cdp_url: str,
    videos_dir: Path,
    renders_dir: Path,
    concept_id: int | None = None,
    model: str | None = None,
    again: bool = False,
    limit: int | None = None,
    log=print,
) -> dict:
    """Grade the winning format's examples and every clip of ours that is not graded yet."""
    from .research.tiktok_browser import fetch_video_sync

    migrate(store)
    concept = (
        next(iter(store.rows("SELECT * FROM concepts WHERE id=?", (concept_id,))), None)
        if concept_id
        else winning_concept(store)
    )
    done = {r["key"] for r in grades(store)} if not again else set()
    graded = {"winners": 0, "ours": 0, "failed": []}
    todo = 0
    for v in winners(store, concept):
        if f"v:{v['id']}" in done or (limit and todo >= limit):
            continue
        todo += 1
        path = Path(v["local_path"] or "")
        if not v.get("local_path") or not path.exists():
            path = videos_dir / f"{v['id']}.mp4"
            try:
                fetch_video_sync(v["url"], path, cdp_url)
            except Exception as e:  # noqa: BLE001 - one unfetchable video must not stop the rest
                graded["failed"].append(f"{v['id']}: {e!r}")
                log(f"{v['id']}: {e!r}")
                continue
            store.set_local_path(v["id"], str(path))
        try:
            res = grade_video(path, {**v, "label": "A top video in the format"}, model=model)
        except Exception as e:  # noqa: BLE001
            graded["failed"].append(f"{v['id']}: {e!r}")
            log(f"{v['id']}: {e!r}")
            continue
        save(store, WINNER, res, video_id=v["id"])
        graded["winners"] += 1
        log(f"winner {v['id']} {res['run']['latency_s']}s {res['grade']['content'][:80]}")
    for c in our_clips(store):
        if f"s:{c['script_id']}" in done or (limit and todo >= limit):
            continue
        todo += 1
        try:
            path = _our_file(c, renders_dir)
            res = grade_video(path, {"label": "Our clip", "desc": c.get("hook")}, model=model)
        except Exception as e:  # noqa: BLE001
            graded["failed"].append(f"s{c['script_id']}: {e!r}")
            log(f"s{c['script_id']}: {e!r}")
            continue
        save(store, OURS, res, script_id=c["script_id"])
        graded["ours"] += 1
        log(f"ours s{c['script_id']} {res['run']['latency_s']}s {res['grade']['content'][:80]}")
    graded["concept"] = {"id": concept["id"], "name": concept["name"]} if concept else None
    return graded


def must_have(winner_grades: list[dict]) -> list[dict]:
    """For each variable, the value most of the winners share, with how many share it."""
    out = []
    n = len(winner_grades)
    if not n:
        return out
    for key, label in VARIABLES:
        values = Counter(str(g.get(key)) for g in winner_grades if g.get(key) is not None)
        if not values:
            continue
        value, k = values.most_common(1)[0]
        out.append(
            {
                "variable": key,
                "label": label,
                "value": value,
                "text": word(value),
                "share": round(k / n, 2),
                "n": n,
                "agreed": k > n / 2,
            }
        )
    return out


def differences(grade: dict, must: list[dict]) -> list[dict]:
    """The variables where this clip is not what the winners share."""
    out = []
    for m in must:
        if not m["agreed"]:
            continue
        ours = grade.get(m["variable"])
        if ours is None or str(ours) == m["value"]:
            continue
        out.append(
            {
                "variable": m["variable"],
                "label": m["label"],
                "ours": word(ours),
                "winners": m["text"],
                "share": m["share"],
            }
        )
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def candidates(rows: list[dict], field: str, kind: str | None = None) -> list[dict]:
    """The open-field answers grouped by wording, most frequent first: the variables the model
    keeps naming that the rubric does not have yet."""
    c: Counter = Counter()
    text: dict[str, str] = {}
    for r in rows:
        if kind and r.get("kind") != kind:
            continue
        for s in r.get("grade", {}).get(field) or []:
            k = _norm(s)
            if k:
                c[k] += 1
                text.setdefault(k, s.strip())
    return [{"text": text[k], "n": n} for k, n in c.most_common(12)]


def report(store: Store) -> dict:
    """Everything the page needs: the winners' grades, ours, the must-have list, each clip's
    differences, and the candidate variables."""
    rows = grades(store)
    win = [r for r in rows if r["kind"] == WINNER]
    ours = [r for r in rows if r["kind"] == OURS]
    must = must_have([r["grade"] for r in win])
    for r in ours:
        r["differences"] = differences(r["grade"], must)
    hooks = {
        s["id"]: s["hook"]
        for s in store.rows(
            "SELECT id, hook FROM scripts WHERE id IN (%s)"
            % (",".join(str(int(r["script_id"])) for r in ours) or "NULL")
        )
    }
    for r in ours:
        r["hook"] = hooks.get(r["script_id"])
    return {
        "rubric_version": RUBRIC_VERSION,
        "variables": [{"variable": k, "label": v} for k, v in VARIABLES],
        "winners": win,
        "ours": ours,
        "must_have": must,
        "candidates": {
            "hurt": candidates(rows, "hurt", OURS),
            "helped": candidates(rows, "helped", WINNER),
        },
    }
