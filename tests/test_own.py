import json
import time

import pytest

from marketing_agent.own import accounts, add_account, match_script, own_posts, own_rewards
from marketing_agent.policy import concept_scores
from marketing_agent.store import Store
from tests.test_cohort import _video


def test_own_posts_feed_the_picker(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    add_account(store, "@OurRing", "#ringlab", "smart ring")
    assert (
        accounts(store)[0]["handle"] == "ourring"
        and accounts(store)[0]["campaign_tag"] == "ringlab"
    )
    now = int(time.time())
    cid = store.insert(
        "concepts",
        {
            "niche": "wearables",
            "name": "Transformation reveal",
            "description": "",
            "early_score": 100,
            "created_at": now,
        },
    )
    sid = store.insert(
        "scripts",
        {
            "concept_id": cid,
            "product": "ring",
            "created_at": now,
            "hook": "before I had sleep data vs after",
            "body": "",
            "demo_score": 5,
            "payload": json.dumps({"captions": ["week one", "week four"]}),
        },
    )
    assert match_script(store, "before I had sleep data vs after #ringlab #smartring")[0] == sid
    assert match_script(store, "totally unrelated cat video")[0] is None
    # a post from our account, baseline from 3 older posts
    for i, views in ((1, 1000), (2, 1000), (3, 1000)):
        store.upsert_video(_video(i, "ourring", 500, views))
    post = _video(9, "ourring", 10, 5000)
    store.upsert_video(post)
    with store.conn() as c:
        c.execute("UPDATE videos SET ours=1, script_id=?, cohort_at=? WHERE id='9'", (sid, now))
    from marketing_agent.cohort import snapshot_creator

    snapshot_creator(store, "ourring")
    p = own_posts(store)[0]
    assert p["script_id"] == sid and p["concept"] == "Transformation reveal"
    assert p["lift_72h"] is None and round(p["lift_now"], 2) == 0.70  # log10(5000/1000)
    rw = own_rewards(store)
    assert rw[cid]["n"] == 1 and 0 < rw[cid]["mean_reward"] < 0.70  # age-discounted
    cs = concept_scores(store, "wearables")
    assert cs[0]["n"] == 1 and cs[0]["mean_reward"] == rw[cid]["mean_reward"]


def test_registration_update_preserves_start_time(tmp_path):
    from unittest.mock import patch

    store = Store(tmp_path / "t.sqlite")
    with patch("marketing_agent.own.time.time", return_value=100):
        add_account(store, "@OurRing", "#ringlab", "smart ring")
    with patch("marketing_agent.own.time.time", return_value=200):
        add_account(store, "OURRING", "", "new product")
    assert accounts(store)[0] == {
        "handle": "ourring",
        "campaign_tag": "",
        "product": "new product",
        "added_at": 100,
    }


def test_profile_sync_keeps_history_out_of_campaign_rewards(tmp_path, monkeypatch):
    from marketing_agent.own import sync_own
    from marketing_agent.research import tiktok_auth, tiktok_browser

    store = Store(tmp_path / "t.sqlite")
    add_account(store, "ourring", "", "ring")
    now = int(time.time())
    cid = store.insert("concepts", {"name": "ring demo", "niche": "wearables"})
    sid = store.insert(
        "scripts",
        {
            "concept_id": cid,
            "hook": "sleep data is useful",
            "payload": "{}",
            "product": "ring",
            "created_at": now - 10,
        },
    )
    # Old content deliberately has an identical caption: it must not be attributed to this script.
    old = dict(_video(1, "ourring", 100, 1000), desc="sleep data is useful")
    fresh = dict(_video(2, "ourring", 0, 5000), desc="sleep data is useful")
    unrelated = _video(3, "someoneelse", 0, 900000)
    monkeypatch.delenv("TIKTOK_POST_HANDLE", raising=False)
    monkeypatch.setattr(tiktok_auth, "ensure_login_sync", lambda cdp, handle: "reused")
    monkeypatch.setattr(
        tiktok_browser,
        "scrape_profile_sync",
        lambda *args, **kwargs: [old, fresh, fresh, unrelated],
    )
    monkeypatch.setattr(tiktok_browser, "profile_stats", lambda handle: {})
    result = sync_own(store, "cdp", "wearables", [])
    assert result == {"accounts": 1, "source": "profile", "found": 2, "new": 1, "historical": 1}
    assert store.rows("SELECT ours, script_id, cohort_at FROM videos WHERE id='1'")[0] == {
        "ours": 0,
        "script_id": None,
        "cohort_at": None,
    }
    assert not store.rows("SELECT * FROM videos WHERE id='3'")
    posts = own_posts(store)
    assert len(posts) == 1 and posts[0]["script_id"] == sid
    assert posts[0]["baseline_log"] == 3
    assert sync_own(store, "cdp", "wearables", [])["new"] == 0


def test_profile_sync_auth_failure_never_falls_back(tmp_path, monkeypatch):
    import pytest

    from marketing_agent.own import sync_own
    from marketing_agent.research import tiktok_auth, tiktok_browser

    store = Store(tmp_path / "t.sqlite")
    add_account(store, "ourring", "tag")

    def fail(*args):
        raise tiktok_auth.LoginRequired("verification required")

    def forbidden(*args, **kwargs):
        raise AssertionError("must not silently fall back")

    monkeypatch.setattr(tiktok_auth, "ensure_login_sync", fail)
    monkeypatch.setattr(tiktok_browser, "scrape_hashtag_sync", forbidden)
    with pytest.raises(tiktok_auth.LoginRequired):
        sync_own(store, "cdp", "wearables", [])
    assert store.rows("SELECT * FROM videos") == []


def test_explicit_hashtag_fallback_deduplicates_posts(tmp_path, monkeypatch):
    from marketing_agent.own import sync_own
    from marketing_agent.research import tiktok_auth, tiktok_browser

    store = Store(tmp_path / "t.sqlite")
    add_account(store, "ourring", "tag")
    row = _video(1, "ourring", 0, 20)

    def forbidden(*args, **kwargs):
        raise AssertionError("hashtag fallback does not need a login")

    monkeypatch.setattr(tiktok_auth, "ensure_login_sync", forbidden)
    monkeypatch.setattr(tiktok_browser, "scrape_hashtag_sync", lambda *a, **kw: [row, row])
    monkeypatch.setattr(tiktok_browser, "profile_stats", lambda handle: {})
    result = sync_own(store, "cdp", "wearables", ["another_tag"], source="hashtag")
    assert result["found"] == result["new"] == 1
    assert own_rewards(store) == {}


def test_script_matching_filters_future_and_other_product_niche(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    now = int(time.time())
    for niche, product, created in [
        ("wearables", "ring", now + 20),
        ("wearables", "glasses", now - 10),
        ("tanning", "ring", now - 10),
    ]:
        cid = store.insert("concepts", {"name": "demo", "niche": niche})
        store.insert(
            "scripts",
            {
                "concept_id": cid,
                "hook": "data changed my life",
                "payload": "{}",
                "product": product,
                "created_at": created,
            },
        )
    assert (
        match_script(
            store, "data changed my life", posted_at=now, niche="wearables", product="ring"
        )[0]
        is None
    )


def test_add_post_links_script_before_public(tmp_path, monkeypatch):
    from marketing_agent import own
    from marketing_agent.research import tiktok_browser

    store = Store(tmp_path / "t.sqlite")
    add_account(store, "@kriscaroll", "", "app")
    cid = store.insert("concepts", {"name": "tv demo", "niche": "fitness"})
    sid = store.insert(
        "scripts",
        {
            "concept_id": cid,
            "product": "app",
            "created_at": int(time.time()) - 60,
            "hook": "POV: cardio finally got fun",
            "body": "",
            "demo_score": 5,
            "payload": json.dumps({"captions": ["POV: cardio finally got fun"]}),
        },
    )
    monkeypatch.setattr(tiktok_browser, "poll_public_stats", lambda url: None)
    url = "https://www.tiktok.com/@kriscaroll/video/7700861920710036749"
    res = own.add_post(store, url, "POV: cardio finally got fun #immersiveworkout", niche="fitness")
    assert res["script_id"] == sid and res["public"] is False
    post = own_posts(store)[0]
    assert post["id"] == "7700861920710036749" and post["script_id"] == sid
    assert post["views_now"] is None and post["n_obs"] == 0
    # once public, the poll fills in the numbers and keeps the link
    monkeypatch.setattr(
        tiktok_browser,
        "poll_public_stats",
        lambda url: {
            **_video("7700861920710036749", "kriscaroll", 1, 2000),
            "desc": "POV: cardio finally got fun",
        },
    )
    res = own.add_post(store, url, niche="fitness")
    assert res["public"] is True and own_posts(store)[0]["views_now"] == 2000
    monkeypatch.setattr(tiktok_browser, "poll_public_stats", lambda url: None)
    with pytest.raises(ValueError):
        own.add_post(store, "https://www.tiktok.com/@someoneelse/video/1", niche="fitness")
