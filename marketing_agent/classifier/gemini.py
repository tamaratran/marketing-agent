"""Whole video, with sound, into Gemini: the labels frames-plus-transcript cannot give (playback
speed, camera moves, a timed shot list, spoken vs on-screen hook, lip sync, timed text overlays,
what the product does second by second). Same VideoTags fields as the frame classifier, so research
videos and our clips keep one vocabulary; the extra fields ride along in the same tags dict."""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from . import rubric as rubric_cfg
from .schema import PROMPT_VERSION, VideoTags

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
INLINE_LIMIT = 18 * 1024 * 1024  # inline_data takes up to 20 MB per request

SYSTEM = """You label short vertical TikTok videos for a marketing team that wants to learn which
formats and hooks earn organic views. Watch the whole clip with sound. Use the post context
(caption, sound, hashtags): the concept is often in the caption. Timestamps are seconds from the
start. Be concrete: name the game or app on any screen, quote on-screen text exactly, say whether
the hook is spoken, written on screen, or only in the caption. Text fields with nothing to say are an empty string, never the word None.
quality_issues lists anything that
looks fake or AI-made, warped hands or faces, a screen whose content changes or does not match the
caption, audio that does not match the picture, or bad edits. A screen that shows one game or
app and then a different one later in the clip is always a quality issue: name both and the
second it switches. Fill in every rubric field from what you see and hear; describe people only as
they look on screen. Return JSON matching the schema."""

Rubric = rubric_cfg.model()


class Shot(BaseModel):
    t_s: float = Field(description="Start, seconds from the beginning")
    seconds: float = Field(description="How long the shot lasts")
    camera: str = Field(
        description="Framing and movement: static medium, handheld selfie, tilt down, zoom in, screen capture"
    )
    what: str = Field(description="What happens on screen and in the audio, one line")


class TextOverlay(BaseModel):
    t_s: float
    text: str = Field(description="The on-screen text, quoted exactly")
    position: str = Field(description="top, centre, bottom, or over the subject")


class ProductMoment(BaseModel):
    t_s: float
    what: str = Field(description="What the product, app or game is doing on screen at that moment")


class DetailedTags(VideoTags):
    playback: Literal["real_time", "sped_up", "slowed", "mixed"] = Field(
        description="Is the footage played at real speed, sped up, slowed down, or a mix"
    )
    hook_spoken: bool = Field(description="Is the hook said out loud in the first 2 seconds")
    hook_on_screen: bool = Field(description="Is the hook written on screen in the first 2 seconds")
    lip_sync: bool = Field(description="Does a visible speaker's mouth match the speech")
    shots: list[Shot] = Field(description="Every shot in order, like an edit list")
    text_overlays: list[TextOverlay] = Field(description="Every piece of on-screen text, in order")
    product_timeline: list[ProductMoment] = Field(
        description="Each moment the product, app or game is on screen, in order"
    )
    rubric: Rubric = Field(description="The video rubric, one answer per variable")


TEXT_FIELDS = {k for k, f in DetailedTags.model_fields.items() if f.annotation is str}
RUBRIC_TEXT = {v["key"] for v in rubric_cfg.variables() if v["kind"] == "text"}
EMPTY_WORDS = {"none", "null", "n/a"}


def _context(meta: dict) -> str:
    return (
        f"Caption: {meta.get('desc', '')}\nSound: {meta.get('music', '')}\n"
        f"Hashtags: {', '.join(meta.get('hashtags') or [])}\nDuration: {meta.get('duration')}s"
    )


def _post(url: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"content-type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"gemini {e.code}: {e.read()[:300]!r}") from None


def label_video(
    video: Path,
    meta: dict,
    model: str | None = None,
    api_key: str | None = None,
    post=_post,
    timeout: float = 300,
) -> dict:
    """Return {"tags": DetailedTags dict, "run": processing metadata}, the shape classify() returns."""
    model = model or os.environ.get("MKT_VIDEO_LABEL_MODEL", "gemini-flash-latest")
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    data = video.read_bytes()
    if len(data) > INLINE_LIMIT:
        raise RuntimeError(f"{video.name} is {len(data) // 1_000_000} MB, over the inline limit")
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
            "responseJsonSchema": DetailedTags.model_json_schema(),
            "temperature": 0.2,
        },
    }
    resp = post(ENDPOINT.format(model=model) + f"?key={api_key}", body, timeout)
    text = resp["candidates"][0]["content"]["parts"][0]["text"]
    raw = json.loads(text)
    for doc, keys in ((raw, TEXT_FIELDS), (raw.get("rubric") or {}, RUBRIC_TEXT)):
        for k in keys:  # the model sometimes writes the word None for an empty text field
            if isinstance(doc.get(k), str) and doc[k].strip().lower() in EMPTY_WORDS:
                doc[k] = ""
    tags = DetailedTags.model_validate(raw)
    usage = resp.get("usageMetadata") or {}
    return {
        "tags": tags.model_dump(),
        "run": {
            "model": model,
            "prompt_version": PROMPT_VERSION + "-video",
            "latency_s": round(time.time() - t0, 1),
            "input_tokens": usage.get("promptTokenCount"),
            "output_tokens": usage.get("candidatesTokenCount"),
            "transcript": None,
            "frame_times": None,
            "watched": "whole video with sound",
            "rubric_version": rubric_cfg.version(),
        },
    }
