"""Format cloning: learn the shape of the product's own proven TikToks, not a summary of them.

The concept radar clusters fresh niche videos (under 72h) into formats. That misses the videos
that actually sell the product, which are usually older and already in the db from the hashtag
scrapes. This module ranks those product videos by views (discounted for account size), watches
the top few (frames + transcript) and writes a beat sheet: what the first two seconds show, how
the hook is delivered, the shot sequence with timings, the pacing, how much on-screen text there
is, and the sound. The beat sheet is stored as a concept (kind "format") so the picker, the
script writer and the dashboard treat it like any other concept, except the scripts have to
follow it beat for beat and carry the sound the human should pick when posting.
"""

import base64
import json
import math
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, Field

from ..store import Store

FORMAT_KIND = "format"


def _mentions(row: dict, needles: list[str]) -> bool:
    """Does the caption (text or hashtags) name the product? The scrape's source_tag is not
    enough: a #subwaysurfers search returns plain gameplay, a #immersiveworkout search returns
    anything the ranking felt like. A needle written `a+b` requires every part (so
    `subwaysurfers+cardio` is the cardio format, not the game)."""
    try:
        hashtags = json.loads(row.get("hashtags") or "[]")
    except (TypeError, ValueError):
        hashtags = []
    text = ((row.get("desc") or "") + " " + " ".join(hashtags)).lower().replace(" ", "")
    return any(all(part in text for part in n.split("+") if part) for n in needles)


def source_score(views: int, followers: int) -> float:
    """Log views, discounted for account size: a 3.7M post from a 1.4k-follower account is a
    format that works; a 3.7M post from a 2M-follower account is an audience."""
    return round(math.log10((views or 0) + 1) - 0.35 * math.log10((followers or 0) + 10), 3)


def product_sources(
    store: Store,
    product_tags: list[str],
    limit: int = 5,
    max_duration_s: int = 60,
    min_views: int = 10_000,
    per_author: int = 2,
) -> list[dict]:
    """The product's best-performing videos in the db, any age: captioned or hashtagged with one
    of `product_tags` (`a+b` means both must appear). Short enough to clone in a 12s clip, at most
    `per_author` per account so one creator does not define the format alone."""
    needles = [t.lower().lstrip("#") for t in product_tags if t.strip()]
    if not needles:
        return []
    rows = store.rows(
        """SELECT v.*, o.views, o.likes FROM videos v JOIN observations o ON o.video_id=v.id
           WHERE o.observed_at=(SELECT MAX(observed_at) FROM observations WHERE video_id=v.id)
             AND COALESCE(v.ours,0)=0 AND (o.views>=?)"""
        + (" AND v.duration<=?" if max_duration_s else ""),
        (min_views, max_duration_s) if max_duration_s else (min_views,),
    )
    cands = [r for r in rows if _mentions(r, needles)]
    for r in cands:
        r["source_score"] = source_score(r.get("views") or 0, r.get("followers") or 0)
    cands.sort(key=lambda r: -r["source_score"])
    out, seen = [], Counter()
    for r in cands:
        if seen[r["author"]] >= per_author:
            continue
        seen[r["author"]] += 1
        out.append(r)
        if len(out) >= limit:
            break
    return out


def common_sound(sources: list[dict]) -> tuple[str, str]:
    """The sound most of the sources share (title, TikTok sound id). Original sounds do not count
    as shared: 'original sound' on two videos is two different sounds."""
    c: Counter = Counter()
    ids: dict[str, str] = {}
    for s in sources:
        title = (s.get("music") or "").strip()
        if not title or "original" in title.lower():
            continue
        c[title] += 1
        ids.setdefault(title, s.get("sound_id") or "")
    if not c:
        return "", ""
    title = c.most_common(1)[0][0]
    return title, ids.get(title, "")


class Beat(BaseModel):
    start_s: float
    end_s: float
    shot: str = Field(description="What is on screen: framing, subject, action, speed")
    audio: str = Field(description="What is heard: spoken words, sound, silence")


class FormatSheet(BaseModel):
    name: str = Field(description="Short name for this format, under 8 words")
    hook_shot: str = Field(description="What the viewer sees in seconds 0 to 2, concretely")
    hook_delivery: Literal["spoken", "text", "visual"] = Field(
        description="How the hook lands: a spoken line, an on-screen line, or purely the image"
    )
    hook_examples: list[str] = Field(description="The actual opening lines of the source videos")
    beats: list[Beat] = Field(description="The shot sequence a clone must follow, 3 to 6 beats")
    pacing: str = Field(description="Cut rhythm and playback speed, e.g. 'gameplay sped up 2-3x'")
    on_screen_text_lines: int = Field(
        ge=0, le=3, description="How many on-screen text lines the sources typically show"
    )
    text_budget_words: int = Field(
        ge=0, le=12, description="Max words per on-screen line that fits the sources' style"
    )
    talking: str = Field(description="If anyone talks: tone, how much, what about. Else 'none'")
    typical_duration_s: int
    dont: list[str] = Field(description="Things the clones must not do that the sources never do")
    summary: str = Field(description="Two sentences a scriptwriter could clone the format from")


SHEET_PROMPT = """You are reverse-engineering a TikTok format for a team that will clone it for
the same product. You get the top-performing videos about the product: for each, its metadata,
frames sampled every {every_s}s in order, and the audio transcript. Describe the FORMAT they share
(what the camera shows, when, at what speed, what is said, how much text is on screen), not the
topic. Be concrete and literal: 'sweaty person in a living room, chest up, talking to the camera'
beats 'engaging hook'. If the videos differ, describe the one with the most views and note the
difference in `dont` or `summary`. Timings in `beats` should fit a {clip_s} second clip."""


def _frames_b64(video: Path, every_s: float, width: int, max_frames: int) -> list[str]:
    from ..classifier.classify import sample_frames

    with tempfile.TemporaryDirectory() as d:
        frames = sample_frames(video, every_s, width, Path(d))
        if len(frames) > max_frames:
            step = len(frames) / max_frames
            frames = [frames[int(i * step)] for i in range(max_frames)]
        return [
            "data:image/jpeg;base64," + base64.b64encode(f.read_bytes()).decode() for f in frames
        ]


def watch_sources(
    store: Store,
    sources: list[dict],
    cdp_url: str,
    model: str = "gpt-5.4",
    transcribe_model: str = "gpt-4o-mini-transcribe",
    every_s: float = 1.5,
    max_frames: int = 10,
    clip_s: int = 12,
    client: OpenAI | None = None,
) -> FormatSheet:
    """Download what is missing, sample frames, transcribe, and ask the model for the beat sheet."""
    from ..classifier.classify import transcribe
    from ..config import settings
    from .tiktok_browser import fetch_video_sync

    client = client or OpenAI()
    content: list[dict] = [
        {"type": "input_text", "text": SHEET_PROMPT.format(every_s=every_s, clip_s=clip_s)}
    ]
    for s in sources:
        path = Path(s["local_path"]) if s.get("local_path") else None
        if not path or not path.exists():
            path = settings.videos_dir / f"{s['id']}.mp4"
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                fetch_video_sync(s["url"], path, cdp_url)
                store.set_local_path(s["id"], str(path))
            except Exception as e:  # noqa: BLE001 - one undownloadable source must not kill the sheet
                content.append(
                    {"type": "input_text", "text": f"\n[{s['id']} could not be downloaded: {e}]"}
                )
                path = None
        header = (
            f"\n=== VIDEO {s['id']} by @{s['author']} ({s.get('followers')} followers) | "
            f"{s.get('views')} views | {s.get('duration')}s | sound: {s.get('music') or '?'} | "
            f"caption: {(s.get('desc') or '')[:200]}"
        )
        content.append({"type": "input_text", "text": header})
        if path:
            for b64 in _frames_b64(path, every_s, 360, max_frames):
                content.append({"type": "input_image", "image_url": b64, "detail": "low"})
            text = transcribe(path, client, transcribe_model)
            content.append({"type": "input_text", "text": f"transcript: {text or '(no speech)'}"})
    resp = client.responses.parse(
        model=model, input=[{"role": "user", "content": content}], text_format=FormatSheet
    )
    return resp.output_parsed


def store_format(
    store: Store, niche: str, product_tags: list[str], sources: list[dict], sheet: FormatSheet
) -> dict:
    """Save the beat sheet as a concept of kind 'format'. The name is stable per product so the
    picker's dedupe-by-name keeps the newest sheet and own-post rewards stay attached."""
    sound, sound_id = common_sound(sources)
    payload = {
        "kind": FORMAT_KIND,
        "name": f"Clone: {sheet.name}",
        "description": sheet.summary,
        "hook_pattern": f"{sheet.hook_delivery}: {sheet.hook_shot}",
        "video_ids": [s["id"] for s in sources],
        "product_tags": product_tags,
        "sound": sound,
        "sound_id": sound_id,
        "sources": [
            {
                "id": s["id"],
                "url": s["url"],
                "author": s["author"],
                "views": s.get("views"),
                "followers": s.get("followers"),
                "duration": s.get("duration"),
                "music": s.get("music"),
            }
            for s in sources
        ],
        "beat_sheet": sheet.model_dump(),
    }
    cid = store.insert(
        "concepts",
        {
            "niche": niche,
            "created_at": int(time.time()),
            "name": payload["name"],
            "description": sheet.summary,
            "video_ids": json.dumps(payload["video_ids"]),
            "early_score": max((s.get("views") or 0) for s in sources) / 1000 if sources else 0,
            "payload": json.dumps(payload),
        },
    )
    return {**payload, "id": cid}


def build_format(
    store: Store,
    niche: str,
    product_tags: list[str],
    cdp_url: str,
    model: str = "gpt-5.4",
    limit: int = 5,
    client: OpenAI | None = None,
) -> dict | None:
    """product_sources -> watch_sources -> store_format. None when the db has no product videos
    worth cloning yet (first run on a new product); the niche concepts are the fallback then."""
    sources = product_sources(store, product_tags, limit=limit)
    if not sources:
        return None
    sheet = watch_sources(store, sources, cdp_url, model=model, client=client)
    return store_format(store, niche, product_tags, sources, sheet)
