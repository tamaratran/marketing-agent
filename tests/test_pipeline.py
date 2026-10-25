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
        "Stop tanning like this", ["[0:00-0:02] hook", "0:02-0:05 show app"], 8.0
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


def test_policy_prefers_observed_winner(tmp_path):
    import random

    from marketing_agent.policy import pick_concept
    from marketing_agent.store import Store

    store = Store(tmp_path / "p.sqlite")
    for name, early in (("Loud", 900), ("Quiet", 5)):
        store.insert(
            "concepts",
            {
                "niche": "x",
                "created_at": 1,
                "name": name,
                "description": "",
                "video_ids": "[]",
                "early_score": early,
                "payload": "{}",
            },
        )
    old = 1_700_000_000
    for i, (concept, views) in enumerate(
        [("Quiet", 5000), ("Quiet", 8000), ("Loud", 100), ("Loud", 120)]
    ):
        store.upsert_video(
            {
                "id": f"v{i}",
                "url": "",
                "author": f"a{i}",
                "followers": 10,
                "create_time": old,
                "duration": 10,
                "desc": "",
                "music": "",
                "hashtags": [],
                "source_tag": "x",
                "views": views,
                "likes": 0,
                "comments": 0,
                "shares": 0,
                "saves": 0,
            },
            observed_at=old + 10,
        )
        store.save_tags(f"v{i}", "m", {"tags": {"concept": concept, "hook_type": "pov"}})
    picks = [pick_concept(store, "x", random.Random(s))["name"] for s in range(50)]
    assert picks.count("Quiet") > 35  # observed reward beats the radar prior


def test_creator_ops_roundtrip(tmp_path):
    import json
    import time

    from marketing_agent.creators.ops import (
        add_creator,
        create_brief,
        creator_report,
        payouts,
        record_post,
    )
    from marketing_agent.store import Store

    store = Store(tmp_path / "t.sqlite")
    sid = store.insert(
        "scripts",
        {
            "concept_id": 1,
            "product": "Glow",
            "created_at": 1,
            "hook": "POV: you see the tan before you book",
            "body": "x",
            "demo_score": 5,
            "payload": json.dumps(
                {
                    "hook": "POV: you see the tan before you book",
                    "captions": ["0:03-0:06 open Glow", "pick shade"],
                }
            ),
        },
    )
    b = create_brief(store, "Glow", [sid], rate_per_1k=1.5, cap_usd=100, deadline_days=3)
    assert "$1.50 per 1,000 views" in b["body"] and "- open Glow" in b["body"]
    add_creator(store, "@amy", "discord", 1.5, followers=1200)
    old = int(time.time()) - 10 * 86400
    record_post(
        store,
        "amy",
        "https://www.tiktok.com/@amy/video/123",
        b["id"],
        sid,
        stats={
            "id": "123",
            "url": "u",
            "author": "amy",
            "followers": 1200,
            "create_time": old,
            "duration": 12,
            "desc": "",
            "music": "",
            "hashtags": [],
            "source_tag": "post",
            "views": 90_000,
            "likes": 1,
            "comments": 0,
            "shares": 0,
            "saves": 0,
        },
    )
    pay = payouts(store)
    assert (
        pay[0]["owed_usd"] == 100.0 and pay[0]["settled"]
    )  # 90k views x $1.5 = 135, capped at 100
    rep = creator_report(store)
    assert rep[0]["posts"] == 1 and rep[0]["status"] == "stalled"
