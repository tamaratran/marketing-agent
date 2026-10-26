import json
import random
import time
from pathlib import Path

from marketing_agent.orchestrator import daily_prompt
from marketing_agent.policy import FORMAT_EDGE, concept_scores, pick_concept
from marketing_agent.research.format import (
    FormatSheet,
    common_sound,
    product_sources,
    source_score,
    store_format,
)
from marketing_agent.store import Store
from marketing_agent.video import scripts as scripts_mod
from marketing_agent.video.edit import captions_from_script
from marketing_agent.video.scripts import format_prompt, write_scripts


def _vid(
    id,
    author,
    views,
    followers,
    duration=14,
    desc="",
    tag="subwaysurfers",
    music="x",
    age_d=30,
    hashtags=None,
):
    return {
        "id": id,
        "url": f"https://www.tiktok.com/@{author}/video/{id}",
        "author": author,
        "followers": followers,
        "create_time": int(time.time()) - age_d * 86400,
        "duration": duration,
        "desc": desc,
        "music": music,
        "hashtags": [tag] if hashtags is None else hashtags,
        "source_tag": tag,
        "views": views,
        "likes": 1,
        "comments": 0,
        "shares": 0,
        "saves": 0,
    }


SHEET = FormatSheet(
    name="Sweaty TV cardio",
    hook_shot="sweaty person chest-up in a living room, TV behind them",
    hook_delivery="spoken",
    hook_examples=["475 calories and I'm still choosing this"],
    beats=[
        {"start_s": 0, "end_s": 2, "shot": "talking head, sweaty", "audio": "spoken hook"},
        {"start_s": 2, "end_s": 12, "shot": "sped up gameplay in front of TV", "audio": "sound"},
    ],
    pacing="gameplay sped up 2-3x",
    on_screen_text_lines=1,
    text_budget_words=5,
    talking="one line at the start",
    typical_duration_s=14,
    dont=["title cards", "explaining in text"],
    summary="Sweaty talking head, then sped-up footage of playing in front of the TV.",
)


def test_product_sources_rank_any_age_small_accounts_first(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    store.upsert_video(_vid("1", "ale", 3_700_000, 1_400, age_d=10))  # old, small, huge: top
    store.upsert_video(_vid("2", "nancy", 20_000_000, 665_000, age_d=60))
    store.upsert_video(_vid("3", "ale", 23_000, 1_400))
    store.upsert_video(_vid("4", "ale", 16_000, 1_400))  # third from same author: dropped
    store.upsert_video(
        _vid("5", "fresh", 34_000, 143_000, tag="coreworkout", age_d=0)
    )  # other topic
    store.upsert_video(_vid("6", "long", 9_000_000, 1_000, duration=75))  # too long to clone
    store.upsert_video(_vid("7", "tiny", 900, 10))  # under min views
    store.upsert_video(_vid("8", "cap", 500_000, 5_000, tag="fyp", desc="Subway Surfers cardio"))
    store.upsert_video(_vid("9", "game", 47_000_000, 1_000, hashtags=[]))
    store.upsert_video(_vid("10", "carnaval", 12_000_000, 8_000, desc="#subwaysurfers #carnaval"))
    out = product_sources(store, ["subwaysurfers"], limit=6)
    # 9 is out: the search tag alone is not a mention; 10 tops 1 on log views minus size
    assert [r["id"] for r in out] == ["10", "1", "2", "8", "3"]
    out = product_sources(store, ["subwaysurfers+cardio"], limit=5)
    assert [r["id"] for r in out] == ["8"]
    assert source_score(3_700_000, 1_400) > source_score(3_700_000, 2_000_000)
    assert product_sources(store, []) == []


def test_common_sound_ignores_original_audio():
    srcs = [
        {"music": "SUBWAY SURFERS (Sped Up)", "sound_id": "9"},
        {"music": "original sound - ale", "sound_id": "1"},
        {"music": "SUBWAY SURFERS (Sped Up)", "sound_id": "9"},
    ]
    assert common_sound(srcs) == ("SUBWAY SURFERS (Sped Up)", "9")
    assert common_sound([{"music": "original sound"}]) == ("", "")


def test_format_concept_outranks_market_concepts(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    store.insert(
        "concepts",
        {
            "niche": "fitness",
            "created_at": 1,
            "name": "Challenge day progression",
            "description": "x",
            "video_ids": "[]",
            "early_score": 999.0,
            "payload": "{}",
        },
    )
    srcs = [{**_vid("1", "ale", 3_700_000, 1_400, music="SUBWAY SURFERS"), "sound_id": "9"}]
    c = store_format(store, "fitness", ["subwaysurfers"], srcs, SHEET)
    assert c["kind"] == "format" and c["sound"] == "SUBWAY SURFERS" and c["video_ids"] == ["1"]
    scores = {s["name"]: s for s in concept_scores(store, "fitness")}
    market = scores["Challenge day progression"]["prior"]
    assert market < 1.1
    assert scores[c["name"]]["prior"] == round(market + FORMAT_EDGE, 3)
    rng = random.Random(0)
    wins = sum(pick_concept(store, "fitness", rng)["id"] == c["id"] for _ in range(2000)) / 2000
    assert 0.8 < wins < 0.97  # favoured, but the market format still gets tested
    saved = json.loads(
        store.rows("SELECT payload FROM concepts WHERE id=?", (c["id"],))[0]["payload"]
    )
    assert saved["beat_sheet"]["pacing"] == "gameplay sped up 2-3x"


def test_format_prompt_carries_beats_sound_and_text_budget():
    concept = {"name": "Clone: x", "sound": "SUBWAY SURFERS", "beat_sheet": SHEET.model_dump()}
    p = format_prompt(concept, "Immersive Workout", n=3)
    assert "2-12s: sped up gameplay in front of TV" in p
    assert '"SUBWAY SURFERS"' in p and "1 line(s) of at most 5 words" in p
    assert "title cards" in p and "Immersive Workout" in p


class _Parsed:
    def __init__(self, scripts):
        self.output_parsed = scripts_mod.ScriptBatch(scripts=scripts)


class _FakeClient:
    last_prompt = ""

    def __init__(self):
        self.responses = self

    def parse(self, model, input, text_format):
        _FakeClient.last_prompt = input[0]["content"]
        return _Parsed(
            [
                scripts_mod.Script(
                    hook="475 calories and I'm still here",
                    body="0-2 talking, 2-12 gameplay",
                    captions=["this is the whole workout honestly", "second line"],
                    product_reveal_s=2,
                    demo_score_1_5=5,
                    why="",
                    video_prompt="sweaty person, then sped up",
                    spoken="475 calories and I'm still here",
                    hook_on_screen=False,
                    sound="",
                )
            ]
        )


def test_write_scripts_from_format_enforces_text_budget_and_sound(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(scripts_mod, "OpenAI", _FakeClient)
    store = Store(tmp_path / "db.sqlite")
    concept = {
        "id": 1,
        "name": "Clone: x",
        "description": "d",
        "sound": "SUBWAY SURFERS",
        "sound_id": "9",
        "beat_sheet": SHEET.model_dump(),
    }
    out = write_scripts(store, concept, "Immersive Workout", n=1)
    assert "Follow it beat for beat" in _FakeClient.last_prompt
    assert out[0]["captions"] == ["this is the whole workout honestly".rsplit(" ", 1)[0]]
    assert out[0]["sound"] == "SUBWAY SURFERS" and out[0]["sound_id"] == "9"
    saved = json.loads(store.rows("SELECT payload FROM scripts")[0]["payload"])
    assert saved["hook_on_screen"] is False and len(saved["captions"]) == 1


def test_spoken_hook_is_not_burned_in():
    assert captions_from_script("", ["one line"], 12)[0].text == "one line"
    assert captions_from_script("text hook", [], 12)[0].text == "text hook"


def test_daily_prompt_passes_product_tags():
    p = daily_prompt("fitness", ["a"], "P", product_tags=["immersiveworkout", "subwaysurfers"])
    assert '--product-tag "immersiveworkout" --product-tag "subwaysurfers"' in p


def test_speech_lines_drops_whisper_hallucinations():
    from marketing_agent.research.format import speech_lines

    segs = [
        {"start": 0.0, "end": 3.7, "text": "♪", "no_speech_prob": 0.1, "avg_logprob": -0.5},
        {
            "start": 3.7,
            "end": 9.0,
            "text": "place water shall flow",
            "no_speech_prob": 0.2,
            "avg_logprob": -1.9,
        },
        {
            "start": 12.5,
            "end": 14.0,
            "text": "Go to Beadaholique.com",
            "no_speech_prob": 0.8,
            "avg_logprob": -0.4,
        },
    ]
    assert speech_lines(segs) == "(no speech, music only)"
    segs.append(
        {
            "start": 0.0,
            "end": 2.0,
            "text": "I burned 475 calories",
            "no_speech_prob": 0.05,
            "avg_logprob": -0.3,
        }
    )
    assert speech_lines(segs) == "0.0-2.0s: I burned 475 calories"


def test_motion_score_separates_moving_from_still(tmp_path):
    import subprocess

    from marketing_agent.research.format import motion_score, speed_label

    still, moving = tmp_path / "still.mp4", tmp_path / "moving.mp4"
    for path, src in ((still, "color=c=gray:s=96x160:r=10"), (moving, "testsrc=s=96x160:r=10")):
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                src,
                "-t",
                "2",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ],
            check=True,
        )
    assert motion_score(still) == 0.0
    assert speed_label(motion_score(still)) == "real time"
    assert motion_score(moving) > 0.0
    assert speed_label(12.0) == "sped up"
    assert speed_label(None) == "unknown"


def test_burned_captions_drop_emoji_the_font_cannot_draw(tmp_path):
    from marketing_agent.video.edit import Caption, drawable, drawtext_filters

    assert drawable("After 402 calories \U0001f635\U0001f4a6") == "After 402 calories"
    assert (
        drawable("POV: cardio \U0001f3c3\U0001f3fd\u200d\u2640\ufe0f finally got fun")
        == "POV: cardio finally got fun"
    )
    drawtext_filters([Caption("burned 475 \U0001f525", 0, 2)], tmp_path)
    assert (tmp_path / "cap0.txt").read_text() == "burned 475"
