import json

from marketing_agent.policy import our_clip_hooks, winning_traits
from marketing_agent.store import Store


def test_rendered_hooks_reach_the_prompt(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    assert our_clip_hooks(store) == ""
    cid = store.insert("concepts", {"name": "tv demo", "niche": "fitness"})
    body = "0-2s: Sweaty selfie close-up, out of breath. 2-4s: cut to jumping in front of the TV."
    sid = store.insert(
        "scripts",
        {
            "concept_id": cid,
            "product": "app",
            "hook": "POV: cardio finally got fun",
            "body": body,
            "demo_score": 5,
            "payload": json.dumps({"body": body}),
        },
    )
    sid2 = store.insert(
        "scripts",
        {
            "concept_id": cid,
            "product": "app",
            "hook": "POV your workout is a game",
            "body": "",
            "demo_score": 5,
        },
    )
    for s in (sid, sid, sid2):
        store.insert("renders", {"script_id": s, "model": "stub", "final_path": f"s{s}.mp4"})
    text = our_clip_hooks(store)
    assert text.startswith("our clips so far (rendered, not yet measured)")
    assert '"POV: cardio finally got fun" (used 2x): 0-2s: Sweaty selfie close-up' in text
    assert '"POV your workout is a game" (used 1x)' in text
    assert "POV: cardio finally got fun" in winning_traits(store)
