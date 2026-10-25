import json
import time

from marketing_agent.cohort import (
    AGES_H,
    build_features,
    enroll,
    features,
    snapshot_creator,
    views_at,
)
from marketing_agent.store import Store


def _video(i, author, age_h, views, followers=5000):
    now = int(time.time())
    return {
        "id": str(i),
        "url": f"https://www.tiktok.com/@{author}/video/{i}",
        "author": author,
        "followers": followers,
        "create_time": now - int(age_h * 3600),
        "duration": 15,
        "desc": "hi #smartring",
        "music": "song",
        "hashtags": ["smartring"],
        "source_tag": "smartring",
        "views": views,
        "likes": 1,
        "comments": 0,
        "shares": 0,
        "saves": 0,
    }


def test_views_at_interpolates_and_refuses_to_extrapolate_far():
    curve = [(1.0, 100), (6.0, 1000), (24.0, 4000)]
    assert views_at(curve, 6) == 1000
    assert 100 < views_at(curve, 3) < 1000
    assert views_at(curve, 168) is None
    assert views_at(curve, 26) is not None  # within 25% of the last observation
    assert views_at([], 1) is None


def test_cohort_enroll_snapshot_and_features(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    fresh = _video(1, "ann", 2, 500)
    old = _video(2, "ann", 400, 20000)
    for v in (fresh, old, _video(3, "ann", 300, 10000), _video(4, "ann", 200, 30000)):
        store.upsert_video(v)
    got = enroll(store, "wearables", [fresh, old])
    assert [r["id"] for r in got] == ["1"]
    row = store.rows("SELECT niche, cohort_at FROM videos WHERE id='1'")[0]
    assert row["niche"] == "wearables" and row["cohort_at"]
    snap = snapshot_creator(store, "ann")
    assert snap["n_posts"] == 4 and snap["median_views"] == 15000
    # a later poll at ~6h gives a 6h point
    later = dict(fresh, views=3000)
    store.upsert_video(later, observed_at=fresh["create_time"] + 6 * 3600)
    assert build_features(store, "wearables") == 1
    f = features(store, "wearables")[0]
    assert f["views_6h"] == 3000 and f["vph_6h"] == 500
    assert f["views_72h"] is None and f["lift_72h"] is None
    assert f["follower_bucket"] == "1k-10k" and f["duration_bucket"] == "10-20s"
    assert f["creator_baseline_log"] is not None and f["tagged"] is False
    assert set(f"views_{a}h" for a in AGES_H) <= set(f)
    assert json.loads(store.rows("SELECT payload FROM features")[0]["payload"])["video_id"] == "1"
