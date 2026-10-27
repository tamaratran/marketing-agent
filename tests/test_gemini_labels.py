"""Gemini video labeller: whole file in, DetailedTags out, through the shared tagger door."""

import json
from pathlib import Path

import pytest

from marketing_agent.classifier import gemini, tagger

FULL = {
    "hook_type": "pov",
    "hook_text": "POV: cardio that doesn't feel like cardio",
    "seconds_until_main_subject": 0.5,
    "visual_style": "realistic_footage",
    "has_voiceover": False,
    "has_on_screen_captions": True,
    "caption_style": "white bold centre",
    "music_role": "trend_sound",
    "pacing_cuts_per_10s": 2.5,
    "concept": "jump to play a body-controlled game in front of the TV",
    "topic": "home cardio",
    "product_or_brand_visible": True,
    "product_on_screen_by_5s": True,
    "cta": "",
    "quality_issues": ["phone shows a different game than the TV"],
    "demo_score_1_5": 5,
    "concept_confidence_0_1": 0.8,
    "summary": "A woman jumps to play a Flappy game on her TV.",
    "beats": [{"t_s": 0, "what": "jumping in front of the TV"}],
    "playback": "sped_up",
    "hook_spoken": False,
    "hook_on_screen": True,
    "lip_sync": False,
    "shots": [{"t_s": 0, "seconds": 3, "camera": "static medium", "what": "jumping"}],
    "text_overlays": [{"t_s": 0, "text": "POV: cardio", "position": "top"}],
    "product_timeline": [{"t_s": 0, "what": "Flappy game on the TV"}],
}


def fake_post(calls):
    def post(url, body, timeout):
        calls.append((url, body))
        return {
            "candidates": [{"content": {"parts": [{"text": json.dumps(FULL)}]}}],
            "usageMetadata": {"promptTokenCount": 1200, "candidatesTokenCount": 500},
        }

    return post


def test_label_video_sends_whole_file_and_returns_detailed_tags(tmp_path: Path):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"\x00" * 2048)
    calls = []
    out = gemini.label_video(
        clip,
        {"desc": "cap", "hashtags": ["a"], "duration": 12},
        model="m",
        api_key="k",
        post=fake_post(calls),
    )
    url, body = calls[0]
    assert url.startswith(gemini.ENDPOINT.format(model="m")) and "key=k" in url
    parts = body["contents"][0]["parts"]
    assert parts[0]["inline_data"]["mime_type"] == "video/mp4"
    assert "Caption: cap" in parts[1]["text"] and "#" not in parts[1]["text"]
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert "shots" in body["generationConfig"]["responseJsonSchema"]["properties"]
    assert out["tags"]["playback"] == "sped_up"
    assert out["tags"]["shots"][0]["camera"] == "static medium"
    assert out["tags"]["hook_type"] == "pov"  # the shared VideoTags fields are still there
    assert out["run"]["model"] == "m" and out["run"]["watched"]
    assert out["run"]["input_tokens"] == 1200


def test_none_word_is_scrubbed_from_text_fields_only(tmp_path: Path):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x")
    doc = dict(FULL, hook_text="None", music_role="none", cta="null")

    def post(url, body, timeout):
        return {"candidates": [{"content": {"parts": [{"text": json.dumps(doc)}]}}]}

    t = gemini.label_video(clip, {}, model="m", api_key="k", post=post)["tags"]
    assert t["hook_text"] == "" and t["cta"] == "" and t["music_role"] == "none"


def test_label_video_refuses_without_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x")
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        gemini.label_video(clip, {}, model="m")


def test_label_video_refuses_oversized_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(gemini, "INLINE_LIMIT", 10)
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x" * 11)
    with pytest.raises(RuntimeError, match="inline limit"):
        gemini.label_video(clip, {}, model="m", api_key="k")


def test_tagger_uses_gemini_when_key_set_else_frames(tmp_path: Path, monkeypatch):
    seen = []
    monkeypatch.setattr(
        gemini,
        "label_video",
        lambda v, m, model=None, api_key=None: seen.append(("gemini", model)) or {},
    )
    import marketing_agent.classifier.classify as cl

    monkeypatch.setattr(
        cl, "classify", lambda v, m, model, tm, client=None: seen.append(("frames", model)) or {}
    )
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x")
    monkeypatch.setattr(tagger.settings, "gemini_api_key", "k")
    monkeypatch.setattr(tagger.settings, "video_label_model", "gemini-x")
    tagger.tag_video(clip, {})
    tagger.tag_video(clip, {}, model="gpt-5.4")  # an explicit gpt model still means frames
    monkeypatch.setattr(tagger.settings, "gemini_api_key", None)
    tagger.tag_video(clip, {})
    assert seen == [
        ("gemini", "gemini-x"),
        ("frames", "gpt-5.4"),
        ("frames", tagger.settings.openai_model),
    ]
