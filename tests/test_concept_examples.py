"""Each concept the API returns carries its most-viewed member videos as examples."""

import json
import time

from marketing_agent.policy import concept_examples, concept_scores
from marketing_agent.store import Store


def _video(store, vid, author, views):
    store.upsert_video(
        {
            "id": vid,
            "url": f"https://www.tiktok.com/@{author}/video/{vid}",
            "author": author,
            "followers": 100,
            "create_time": int(time.time()) - 3600,
            "duration": 10,
            "desc": "",
            "music": "",
            "hashtags": [],
            "source_tag": "fitness",
            "views": views,
        }
    )


def test_examples_are_the_most_viewed_members(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    _video(store, "1", "small", 100)
    _video(store, "2", "big", 5000)
    _video(store, "3", "mid", 900)
    _video(store, "4", "other", 99999)
    ex = concept_examples(store, ["1", "2", "3"], n=2)
    assert [e["author"] for e in ex] == ["big", "mid"]
    assert ex[0]["views"] == 5000 and ex[0]["url"].endswith("/video/2")
    assert concept_examples(store, []) == []


def test_concept_scores_carry_examples(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    _video(store, "1", "a", 10)
    store.insert(
        "concepts",
        {
            "niche": "fitness",
            "created_at": int(time.time()),
            "name": "X",
            "description": "d",
            "video_ids": json.dumps(["1"]),
            "early_score": 5.0,
            "payload": "{}",
        },
    )
    (c,) = concept_scores(store, "fitness")
    assert c["examples"][0]["id"] == "1" and "video_ids" not in c
