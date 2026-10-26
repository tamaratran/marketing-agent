import json

from marketing_agent import learnings
from marketing_agent.policy import verdicts, winning_traits
from marketing_agent.store import Store
from marketing_agent.video.generate import GenRequest, video_prompt


def _world(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    cid = store.insert(
        "concepts",
        {
            "name": "tv demo",
            "niche": "fitness",
            "early_score": 10,
            "created_at": 1,
            "payload": "{}",
        },
    )
    sids = []
    for hook in ("POV: cardio finally got fun", "POV your workout is a game"):
        sids.append(
            store.insert(
                "scripts",
                {
                    "concept_id": cid,
                    "product": "app",
                    "hook": hook,
                    "body": "",
                    "demo_score": 5,
                    "payload": json.dumps({"body": ""}),
                },
            )
        )
    for s in (sids[0], sids[0], sids[1]):
        store.insert("renders", {"script_id": s, "model": "stub", "final_path": f"s{s}.mp4"})
    return store, cid, sids


def test_rendered_hooks_reach_the_prompt_marked_untested(tmp_path, monkeypatch):
    store, _, _ = _world(tmp_path)
    assert verdicts(Store(tmp_path / "empty.sqlite"), "fitness") == ""
    text = verdicts(store, "fitness")
    assert "Never posted: tv demo." in text
    assert '"POV: cardio finally got fun": untested (rendered 2x)' in text
    assert '"POV your workout is a game": untested (rendered 1x)' in text
    assert "frequency means nothing" in text
    assert "Only 0 post(s) measured so far" in text
    assert "POV: cardio finally got fun" in winning_traits(store)


def test_held_clips_drop_out_of_the_hooks_list(tmp_path):
    store, _, sids = _world(tmp_path)
    assert learnings.hold(store, sids[0], "TV shows the wrong game") == 2
    text = verdicts(store, "fitness")
    assert "POV: cardio finally got fun" not in text
    assert "POV your workout is a game" in text
    assert learnings.release(store, sids[0]) == 2
    assert "POV: cardio finally got fun" in verdicts(store, "fitness")
    assert learnings.hold(store, 999, "nothing") == 0


def test_rules_reach_both_prompts(tmp_path):
    store, _, _ = _world(tmp_path)
    assert learnings.rules_text(store) == ""
    learnings.add_rule(
        store, "fitness", "app", "The TV shows our flappy-bird game for the whole clip."
    )
    learnings.add_rule(store, "fitness", "app", "One person only, nobody walks in.")
    assert learnings.rules(store, "fitness") == [
        "The TV shows our flappy-bird game for the whole clip.",
        "One person only, nobody walks in.",
    ]
    text = winning_traits(store)
    assert text.startswith("Standing rules from review (always apply):\n- The TV shows")
    assert text.index("One person only") < text.index("Never posted")
    [rule, *_] = [e for e in learnings.entries(store) if e["kind"] == "rule"]
    assert rule["title"] == "One person only, nobody walks in."
    prompt = video_prompt(
        GenRequest(prompt="A person jogs in front of a TV.", rules=learnings.rules(store))
    )
    assert (
        "A person jogs in front of a TV. The TV shows our flappy-bird game for the whole clip. One person only, nobody walks in."
        in prompt
    )
    assert prompt.endswith("Captions are added afterwards.")
