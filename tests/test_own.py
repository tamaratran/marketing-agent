import json
import time

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
