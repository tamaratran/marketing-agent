import json
import time

from marketing_agent.policy import (
    SHRINK_K,
    TRAITS,
    concept_scores,
    concept_traits,
    pick_concept,
)
from marketing_agent.store import Store
from tests.test_cohort import _video


def _tag(store, vid, hook="pov", style="ugc_selfie", product=False, cuts=1.0):
    store.insert(
        "tags",
        {
            "video_id": vid,
            "model": "t",
            "tagged_at": int(time.time()),
            "payload": json.dumps(
                {
                    "tags": {
                        "hook_type": hook,
                        "visual_style": style,
                        "product_on_screen_by_5s": product,
                        "pacing_cuts_per_10s": cuts,
                    }
                }
            ),
        },
    )


def _concept(store, name, video_ids, early=100, created=None, kind=None):
    payload = {"name": name}
    if kind:
        payload["kind"] = kind
    return store.insert(
        "concepts",
        {
            "niche": "wearables",
            "name": name,
            "description": "",
            "video_ids": json.dumps(video_ids),
            "early_score": early,
            "created_at": created or int(time.time()),
            "payload": json.dumps(payload),
        },
    )


def _post(store, concept_id, vid, views, age_h=48, followers=500):
    sid = store.insert(
        "scripts",
        {
            "concept_id": concept_id,
            "product": "ring",
            "created_at": int(time.time()),
            "hook": f"hook {vid}",
            "body": "",
            "demo_score": 5,
            "payload": "{}",
        },
    )
    store.upsert_video(_video(vid, "ours", age_h, views, followers))
    with store.conn() as c:
        c.execute(
            "UPDATE videos SET ours=1, script_id=?, cohort_at=? WHERE id=?",
            (sid, int(time.time()), vid),
        )
    return sid


def _world(tmp_path):
    """Three reference videos per style so a curve exists, our account snapshot, no posts."""
    store = Store(tmp_path / "t.sqlite")
    for i in range(40):
        store.upsert_video(_video(100 + i, f"c{i}", 24 + i, 1000 + 50 * i, 5000))
    for i, views in ((901, 1000), (902, 1000), (903, 1000)):
        store.upsert_video(_video(i, "ours", 24 * 200 + i, views, 500))  # old: no account offset
    with store.conn() as c:
        c.executemany("UPDATE videos SET ours=1 WHERE id=?", [("901",), ("902",), ("903",)])
    from marketing_agent.cohort import snapshot_creator

    snapshot_creator(store, "ours")
    return store


def test_concept_traits_take_the_majority_and_tolerate_untagged_members(tmp_path):
    store = _world(tmp_path)
    _tag(store, "100", hook="pov", style="ugc_selfie", cuts=1)
    _tag(store, "101", hook="pov", style="talking_head", cuts=5)
    _tag(store, "102", hook="tutorial", style="ugc_selfie", cuts=1)
    t = concept_traits(store, ["100", "101", "102", "103"])
    assert t == {
        "hook_type": "pov",
        "visual_style": "ugc_selfie",
        "product_on_screen_by_5s": False,
        "pacing_bucket": "slow",
    }
    assert concept_traits(store, ["103"]) == dict.fromkeys(TRAITS)


def test_a_flop_teaches_every_format_that_shares_its_traits(tmp_path):
    store = _world(tmp_path)
    for v in ("100", "101"):
        _tag(store, v, hook="pov", style="ugc_selfie")
    for v in ("102", "103"):
        _tag(store, v, hook="tutorial", style="screen_recording", product=True, cuts=5)
    flop = _concept(store, "Selfie POV", ["100", "101"])
    _concept(store, "Mirror POV", ["100"])  # same traits, never posted, different name
    _concept(store, "Screen tutorial", ["102", "103"])
    _post(store, flop, "999", views=1)  # a disaster
    by = {c["name"]: c for c in concept_scores(store, "wearables")}
    assert by["Selfie POV"]["n"] == 1 and by["Selfie POV"]["mean_reward"] < -1
    assert by["Mirror POV"]["n"] == 0 and by["Mirror POV"]["trait_bonus"] < -0.5
    assert by["Mirror POV"]["learned"] == by["Mirror POV"]["trait_bonus"]
    assert abs(by["Screen tutorial"]["trait_bonus"]) < 0.05  # only the niche's faint signal
    # the posted concept's own result still counts for more than its trait guess
    assert by["Selfie POV"]["learned"] < by["Mirror POV"]["learned"]
    detail = {d["trait"]: d for d in by["Mirror POV"]["trait_detail"]}
    assert detail["hook_type"]["ours_n"] == 1 and detail["hook_type"]["ours"] < 0


def test_renamed_format_keeps_what_it_learned_through_its_traits(tmp_path):
    store = _world(tmp_path)
    for v in ("100", "101"):
        _tag(store, v, hook="pov", style="ugc_selfie")
    old = _concept(store, "Selfie POV", ["100", "101"], created=int(time.time()) - 100)
    _post(store, old, "999", views=1)
    # the next research run names it differently; nothing points at the new row
    _concept(store, "POV from the couch", ["100", "101"])
    by = {c["name"]: c for c in concept_scores(store, "wearables")}
    assert by["POV from the couch"]["n"] == 0
    assert by["POV from the couch"]["learned"] < -0.5


def test_own_post_tags_beat_the_concept_profile(tmp_path):
    store = _world(tmp_path)
    _tag(store, "100", hook="tutorial", style="screen_recording", product=True, cuts=5)
    _tag(store, "101", hook="pov", style="ugc_selfie")
    scripted = _concept(store, "Screen tutorial", ["100"])
    _concept(store, "Selfie POV", ["101"])
    _post(store, scripted, "999", views=1)
    _tag(store, "999", hook="pov", style="ugc_selfie")  # the clip we made was really a selfie POV
    by = {c["name"]: c for c in concept_scores(store, "wearables")}
    assert by["Selfie POV"]["trait_bonus"] < -0.5  # the flop lands on what the clip looked like
    assert abs(by["Screen tutorial"]["trait_bonus"]) < 0.05


def test_more_posts_move_learned_from_the_trait_guess_to_the_concepts_own_mean(tmp_path):
    store = _world(tmp_path)
    for v in ("100", "101"):
        _tag(store, v, hook="pov", style="ugc_selfie")
    cid = _concept(store, "Selfie POV", ["100", "101"])
    # five flops and one hit: with 3+ recent posts the account's usual is their median, so the
    # flops sit at 0 and the hit well above it
    for i, views in enumerate((1, 1, 1, 1, 1, 1000)):
        _post(store, cid, str(990 + i), views=views)
    (c,) = concept_scores(store, "wearables")
    assert c["n"] == 6 and c["mean_reward"] > 0.3
    # learned = (K*trait + sum)/(K+n): with n >> K it sits close to the own mean
    assert abs(c["learned"] - c["mean_reward"]) < abs(c["trait_bonus"] - c["mean_reward"])
    assert (
        abs(c["learned"] - (SHRINK_K * c["trait_bonus"] + 6 * c["mean_reward"]) / (SHRINK_K + 6))
        < 0.01
    )


def test_pick_uses_learned_not_raw_mean(tmp_path):
    store = _world(tmp_path)
    for v in ("100", "101"):
        _tag(store, v, hook="pov", style="ugc_selfie")
    _tag(store, "102", hook="tutorial", style="screen_recording", product=True, cuts=5)
    flop = _concept(store, "Selfie POV", ["100"], early=100)
    _concept(store, "Mirror POV", ["101"], early=100)
    _concept(store, "Screen tutorial", ["102"], early=100)
    _post(store, flop, "999", views=1)
    import random

    rng = random.Random(0)
    picks = [pick_concept(store, "wearables", rng)["name"] for _ in range(300)]
    assert picks.count("Screen tutorial") > 200
    assert picks.count("Mirror POV") >= picks.count("Selfie POV")
