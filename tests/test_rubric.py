"""The rubric: the winners and our clips graded alike, the must-have list, each clip's
differences, and the candidate variables."""

import json
import time
from pathlib import Path

from marketing_agent import rubric
from marketing_agent.store import Store

GRADE = {
    "content": "One person copies the TV game in a living room",
    "product_on_screen": "yes_working",
    "screen_text": "flappy bird on the TV",
    "captions": "readable",
    "caption_text": "POV: cardio finally got fun",
    "people": "one",
    "gender": "man",
    "build": "athletic",
    "clothing": "black t-shirt, shorts",
    "sweat": "some",
    "speech": "none",
    "speech_text": "",
    "movement": "fast",
    "activity": "flapping arms, ducking",
    "sound": "trend_sound",
    "sound_fits": True,
    "pacing": "one_shot",
    "looks_fake": [],
    "helped": ["one locked shot", "the game visibly reacts to the body"],
    "hurt": [],
    "first_frame": "a man facing a TV",
    "payoff": "",
    "humor": False,
    "caption_amount": "a_sentence",
    "caption_placement": "top",
    "age": "20s",
    "size_in_frame": "full_body",
    "face_visible": True,
    "clothing_type": "gym_wear",
    "talks_to_camera": False,
    "dance": False,
    "dance_name": "",
    "energy": "high",
    "setting": "living_room",
    "camera": "tripod",
    "lighting": "natural",
    "body_controls_game": "yes",
    "sound_name": "",
    "sound_synced": True,
    "looks_ai_made": False,
}


def _store(tmp_path, monkeypatch):
    monkeypatch.setenv("MKT_DB", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("MKT_DATA_DIR", str(tmp_path))
    store = Store(tmp_path / "db.sqlite")
    now = int(time.time())
    for i, views in enumerate([33_400_000, 19_100_000, 12_100_000]):
        store.upsert_video(
            {
                "id": f"w{i}",
                "url": f"https://www.tiktok.com/@a/video/w{i}",
                "author": "a",
                "followers": 1000,
                "create_time": now - 86400,
                "duration": 12,
                "desc": "",
                "music": "",
                "source_tag": "immersiveworkout",
                "views": views,
            }
        )
    with store.conn() as c:
        c.execute(
            "INSERT INTO concepts (id,niche,created_at,name,description,video_ids,early_score) "
            "VALUES (81,'fitness',?,'Clone: TV follow-along demo','',?,33400.0)",
            (now, json.dumps(["w0", "w1", "w2"])),
        )
        c.execute(
            "INSERT INTO concepts (id,niche,created_at,name,description,video_ids,early_score) "
            "VALUES (1,'fitness',?,'Old giant','',?,99999999.0)",
            (now, json.dumps([])),
        )
        c.execute(
            "INSERT INTO scripts (id,concept_id,created_at,hook) VALUES (95,81,?,'POV: cardio')",
            (now,),
        )
        c.execute(
            "INSERT INTO renders (id,script_id,created_at,final_path) VALUES (1,95,?,?)",
            (now, str(tmp_path / "s95.mp4")),
        )
    (tmp_path / "s95.mp4").write_bytes(b"ours")
    return store


def test_grade_video_sends_the_whole_file_and_validates(tmp_path):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"\x00" * 100)
    calls = []

    def post(url, body, timeout):
        calls.append((url, body))
        return {
            "candidates": [
                {"content": {"parts": [{"text": json.dumps({**GRADE, "speech_text": "None"})}]}}
            ],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
        }

    res = rubric.grade_video(
        clip, {"label": "Our clip", "desc": "hi"}, model="m", api_key="k", post=post
    )
    assert "models/m:generateContent" in calls[0][0]
    parts = calls[0][1]["contents"][0]["parts"]
    assert parts[0]["inline_data"]["mime_type"] == "video/mp4"
    assert "Our clip" in parts[1]["text"]
    assert res["grade"]["speech_text"] == ""  # the word None becomes empty
    assert res["grade"]["movement"] == "fast"
    assert res["run"]["rubric_version"] == rubric.RUBRIC_VERSION


def test_run_grades_the_winners_and_ours_then_reports(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    assert rubric.winning_concept(store)["id"] == 81  # the batch's concept, not the old giant
    fetched = []

    def fetch(url, out, cdp):
        fetched.append(url)
        Path(out).write_bytes(b"win")

    monkeypatch.setattr("marketing_agent.research.tiktok_browser.fetch_video_sync", fetch)
    seen = []

    def grade(video, meta, model=None):
        seen.append((video.name, meta.get("label")))
        g = dict(GRADE)
        if meta.get("label") == "Our clip":
            g.update(
                movement="slow",
                sound="music",
                sound_fits=False,
                hurt=["TV switches game", "no trending sound"],
            )
        elif video.name == "w2.mp4":
            g.update(gender="woman")
        return {
            "grade": g,
            "run": {"model": "m", "latency_s": 1.0, "rubric_version": rubric.RUBRIC_VERSION},
        }

    monkeypatch.setattr(rubric, "grade_video", grade)
    res = rubric.run(
        store, "http://cdp", tmp_path / "videos", tmp_path / "renders", log=lambda *a: None
    )
    assert res == {
        "winners": 3,
        "ours": 1,
        "failed": [],
        "concept": {"id": 81, "name": "Clone: TV follow-along demo"},
    }
    assert len(fetched) == 3 and [s[1] for s in seen].count("Our clip") == 1

    # a second run grades nothing new
    seen.clear()
    assert (
        rubric.run(
            store, "http://cdp", tmp_path / "videos", tmp_path / "renders", log=lambda *a: None
        )["winners"]
        == 0
    )
    assert not seen

    rep = rubric.report(store)
    must = {m["variable"]: m for m in rep["must_have"]}
    assert must["movement"] == {
        "variable": "movement",
        "label": "Movement",
        "value": "fast",
        "text": "fast",
        "share": 1.0,
        "n": 3,
        "agreed": True,
    }
    assert must["gender"]["share"] == 0.67 and must["gender"]["agreed"] is True
    ours = rep["ours"][0]
    assert ours["script_id"] == 95 and ours["hook"] == "POV: cardio"
    assert [(d["label"], d["ours"], d["winners"]) for d in ours["differences"]] == [
        ("Movement", "slow", "fast"),
        ("Sound", "music", "a trending sound"),
        ("Sound fits", "no", "yes"),
    ]
    assert rep["candidates"]["hurt"] == [
        {"text": "TV switches game", "n": 1},
        {"text": "no trending sound", "n": 1},
    ]
    assert rep["candidates"]["helped"][0] == {"text": "one locked shot", "n": 3}
    json.dumps(rep)


def test_must_have_on_nothing():
    assert rubric.must_have([]) == []
    assert rubric.differences(GRADE, []) == []


def test_must_have_counts_only_winners_with_a_person():
    person = {**GRADE, "people": "one", "movement": "fast"}
    screen = {**GRADE, "people": "none", "gender": "none", "movement": "still"}
    must = {m["variable"]: m for m in rubric.must_have([person, person, screen, screen, screen])}
    assert must["people"]["value"] == "one" and must["people"]["n"] == 2
    assert must["movement"]["value"] == "fast" and must["movement"]["share"] == 1.0
    # one person video is too few to lean on: everyone counts
    assert rubric.comparable([person, screen, screen]) == [person, screen, screen]
