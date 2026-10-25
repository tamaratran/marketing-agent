import json
import time
from pathlib import Path

from marketing_agent.classifier.schema import VideoTags
from marketing_agent.research.radar import early_score, rank
from marketing_agent.research.tiktok_browser import _row
from marketing_agent.store import Store
from marketing_agent.video.edit import assemble, captions_from_script, probe_duration
from marketing_agent.video.generate import GenRequest, StubProvider

ITEM = {
    "id": "7",
    "createTime": str(int(time.time()) - 7200),
    "desc": "In the sun for hours tryna tan #tanning #fyp",
    "author": {"uniqueId": "someone"},
    "authorStats": {"followerCount": 5000},
    "video": {"duration": 20},
    "music": {"title": "original sound"},
    "stats": {
        "playCount": 20000,
        "diggCount": 1000,
        "shareCount": 50,
        "commentCount": 5,
        "collectCount": 9,
    },
}


def test_row_and_store_roundtrip(tmp_path: Path):
    row = _row(ITEM, "tanning")
    assert row["hashtags"] == ["tanning", "fyp"]
    assert row["url"].endswith("/@someone/video/7")
    store = Store(tmp_path / "db.sqlite")
    store.upsert_video(row, observed_at=1)
    store.upsert_video({**row, "views": 30000}, observed_at=2)
    latest = store.latest("tanning")
    assert len(latest) == 1 and latest[0]["views"] == 30000
    assert len(store.rows("SELECT * FROM observations")) == 2


def test_early_score_prefers_small_fast_accounts():
    now = int(time.time())
    small = {"create_time": now - 7200, "views": 20000, "followers": 5000}
    big = {"create_time": now - 7200, "views": 20000, "followers": 5_000_000}
    old = {"create_time": now - 7200 * 100, "views": 20000, "followers": 5000}
    assert early_score(small, now) > early_score(big, now) > 0
    assert early_score(small, now) > early_score(old, now)


def test_rank_filters_by_age(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    store.upsert_video(_row(ITEM, "tanning"))
    store.upsert_video(
        _row({**ITEM, "id": "8", "createTime": str(int(time.time()) - 86400 * 10)}, "tanning")
    )
    assert [r["id"] for r in rank(store, "tanning", max_age_h=72)] == ["7"]


def test_tags_schema_accepts_classifier_output():
    payload = {
        "hook_type": "text_on_screen",
        "hook_text": "how many frogs can you find",
        "seconds_until_main_subject": 0,
        "visual_style": "animation",
        "has_voiceover": False,
        "has_on_screen_captions": True,
        "caption_style": "white bold centered",
        "music_role": "trend_sound",
        "pacing_cuts_per_10s": 2,
        "concept": "hidden object count challenge",
        "topic": "minecraft",
        "product_or_brand_visible": False,
        "product_on_screen_by_5s": False,
        "cta": "",
        "quality_issues": [],
        "demo_score_1_5": 4,
        "concept_confidence_0_1": 0.8,
        "summary": "ok",
    }
    assert VideoTags.model_validate(payload).demo_score_1_5 == 4
    assert (
        json.loads(VideoTags.model_validate(payload).model_dump_json())["hook_type"]
        == "text_on_screen"
    )


def test_stub_render_and_edit(tmp_path: Path):
    raw = StubProvider().generate(GenRequest(prompt="x", duration_s=3), tmp_path / "raw.mp4").path
    caps = captions_from_script(
        "Stop tanning like this", ["[0:00-0:02] hook", "0:02-0:05 show app"], 3.0
    )
    assert caps[0].text == "Stop tanning like this" and len(caps) == 3
    assert [c.text for c in caps[1:]] == ["hook", "show app"]
    final = assemble([raw], tmp_path / "final.mp4", captions=caps)
    assert final.exists() and 2.5 < probe_duration(final) < 3.5


def test_scoreboard_rewards_and_flags():
    from marketing_agent.scoreboard import _winsor, rank_by, rewards, shadowban_flags

    now = 2_000_000_000
    old = now - 3 * 86400
    rows = [
        {"id": "a1", "author": "a", "views": 500, "create_time": old, "hook_type": "pov"},
        {"id": "a2", "author": "a", "views": 700, "create_time": old, "hook_type": "pov"},
        {"id": "a3", "author": "a", "views": 300, "create_time": old, "hook_type": "question"},
        {"id": "b1", "author": "b", "views": 1_000_000, "create_time": old, "hook_type": "pov"},
        {"id": "c1", "author": "c", "views": 50_000, "create_time": now - 3600, "hook_type": "pov"},
    ]
    scored = {r["id"]: r for r in rewards(rows, now=now)}
    assert scored["c1"]["reward"] is None  # too young to judge
    assert scored["a2"]["reward"] > 0 > scored["a3"]["reward"]  # relative to a's own median
    assert _winsor([1.0] * 19 + [100.0]) == 1.0  # the outlier is capped at the 95th pct
    hooks = rank_by(list(scored.values()), "hook_type", min_n=1)
    assert hooks[0]["hook_type"] == "pov"
    flags = shadowban_flags(list(scored.values()), now=now)
    assert [f["author"] for f in flags] == ["a"] and flags[0]["max_views"] == 700
