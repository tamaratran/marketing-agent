import math
import time

from marketing_agent.own import own_posts, own_rewards
from marketing_agent.scoreboard import (
    MIN_AGE_H_FOR_OWN,
    MIN_CURVE_POINTS,
    curve_points,
    expected_log,
    fit_curve,
    rewards,
)
from marketing_agent.store import Store
from tests.test_cohort import _video


def _points(n=60):
    # views grow with age^0.7 and followers^0.3, exactly, so the fit must recover both
    pts = []
    for i in range(n):
        age = 1 + (i % 12) * 6
        followers = 10 ** (2 + (i % 5))
        views = 10 ** (1.0 + 0.7 * math.log10(age) + 0.3 * math.log10(followers + 1)) - 1
        pts.append((age, views, followers))
    return pts


def test_fit_curve_recovers_age_and_size_effects():
    c = fit_curve(_points())
    assert c and c["n"] == 60
    assert abs(c["b"] - 0.7) < 0.01 and abs(c["c"] - 0.3) < 0.01 and c["sd"] < 0.01
    # a 3h-old video from a tiny account is expected to have far fewer views than a day-old one
    # from a big account
    assert expected_log(c, 3, 300) < expected_log(c, 24, 300) < expected_log(c, 24, 300_000)


def test_fit_curve_needs_enough_points():
    assert fit_curve(_points(MIN_CURVE_POINTS - 1)) is None
    assert fit_curve([]) is None


def test_rewards_judge_against_videos_of_the_same_age_and_size():
    now = int(time.time())
    rows = []
    for i, (age, views, followers) in enumerate(_points(80)):
        r = _video(i, f"c{i}", age, int(views), followers)
        r["observed_at"] = now
        rows.append(r)
    # a fresh small-account video exactly on the curve: reward about 0 once it is old enough
    on_curve = _video(
        900, "small", 30, int(10 ** expected_log(fit_curve(_points(80)), 30, 300)), 300
    )
    on_curve["observed_at"] = now
    rows.append(on_curve)
    scored = {r["id"]: r for r in rewards(rows, now)}
    assert abs(scored["900"]["reward"]) < 0.05
    assert scored["900"]["creator_offset"] == 0.0  # one video from this creator: no track record


def test_rewards_add_the_creators_track_record():
    now = int(time.time())
    rows = []
    for i, (age, views, followers) in enumerate(_points(80)):
        r = _video(i, f"c{i}", age, int(views), followers)
        r["observed_at"] = now
        rows.append(r)
    # a creator who always does 3x the curve: their fourth video doing 3x is just usual for them
    # (3x, not 10x, so the 95th percentile cap does not bite; the cap is tested by the live data)
    curve = fit_curve(_points(80))
    for j, age in enumerate((30, 40, 50, 60)):
        v = _video(800 + j, "star", age, int(10 ** (expected_log(curve, age, 5000) + 0.5)), 5000)
        v["observed_at"] = now
        rows.append(v)
    scored = {r["id"]: r for r in rewards(rows, now)}
    assert abs(scored["803"]["creator_offset"] - 0.5) < 0.1
    assert abs(scored["803"]["reward"]) < 0.1
    # a stranger with the same views on the same curve gets the full credit
    assert scored["803"]["log_views"] - scored["803"]["expected"] > 0.4


def test_curve_points_use_the_observation_age():
    now = int(time.time())
    r = _video(1, "a", 48, 1000, 100)
    r["observed_at"] = r["create_time"] + 6 * 3600
    ((age, views, followers),) = curve_points([r], now)
    assert round(age) == 6 and views == 1000 and followers == 100
    assert curve_points([{"views": 5}], now) == []


def test_young_post_on_a_cold_account_is_judged_against_its_peers(tmp_path):
    """The account's old viral posts set a huge 'usual'; the picker must instead see how the
    post does against niche videos of the same age from accounts of the same size."""
    store = Store(tmp_path / "t.sqlite")
    now = int(time.time())
    # the niche: 80 reference videos on a known curve
    for i, (age, views, followers) in enumerate(_points(80)):
        store.upsert_video(_video(i, f"c{i}", age, int(views), followers))
    curve = fit_curve(_points(80))
    cid = store.insert(
        "concepts",
        {
            "niche": "wearables",
            "name": "Demo",
            "description": "",
            "early_score": 10,
            "created_at": now,
        },
    )
    sid = store.insert(
        "scripts",
        {
            "concept_id": cid,
            "product": "ring",
            "created_at": now,
            "hook": "h",
            "body": "",
            "demo_score": 5,
            "payload": "{}",
        },
    )
    # our account: three old hits two years ago, 500 followers
    for i, views in ((901, 500_000), (902, 800_000), (903, 1_200_000)):
        store.upsert_video(_video(i, "ours", 24 * 700, views, 500))
    # a 10h-old post exactly on the curve for a 500-follower account
    post = _video(999, "ours", 10, int(10 ** expected_log(curve, 10, 500)), 500)
    store.upsert_video(post)
    with store.conn() as c:
        c.execute("UPDATE videos SET ours=1, script_id=?, cohort_at=? WHERE id='999'", (sid, now))
        c.executemany("UPDATE videos SET ours=1 WHERE id=?", [("901",), ("902",), ("903",)])
    from marketing_agent.cohort import snapshot_creator

    snapshot_creator(store, "ours")
    p = own_posts(store)[0]
    assert p["lift_now"] < -2  # vs the account's old hits it looks like a disaster
    assert abs(p["lift_matched"]) < 0.05  # vs its peers it is exactly usual
    assert p["account_offset"] == 0.0  # two-year-old posts do not set today's usual
    rw = own_rewards(store)
    assert rw[cid]["n"] == 1 and abs(rw[cid]["mean_reward"]) < 0.05


def test_posts_under_six_hours_do_not_move_the_picker(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    now = int(time.time())
    cid = store.insert(
        "concepts",
        {
            "niche": "wearables",
            "name": "Demo",
            "description": "",
            "early_score": 10,
            "created_at": now,
        },
    )
    sid = store.insert(
        "scripts",
        {
            "concept_id": cid,
            "product": "ring",
            "created_at": now,
            "hook": "h",
            "body": "",
            "demo_score": 5,
            "payload": "{}",
        },
    )
    for i, views in ((1, 1000), (2, 1000), (3, 1000)):
        store.upsert_video(_video(i, "ours", 100 + i, views))
    store.upsert_video(_video(9, "ours", MIN_AGE_H_FOR_OWN - 1, 50_000))
    with store.conn() as c:
        c.execute("UPDATE videos SET ours=1, script_id=?, cohort_at=? WHERE id='9'", (sid, now))
    from marketing_agent.cohort import snapshot_creator

    snapshot_creator(store, "ours")
    assert own_posts(store)[0]["lift_now"] > 1
    assert own_rewards(store) == {}
