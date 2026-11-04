"""The prerequisite chain: the rubric's grades become a digest, the digest becomes a learnings
entry (replaced in place on each refresh), and the script prompt carries both the digest and the
recent review notes."""

import time

from marketing_agent import learnings, rubric
from marketing_agent.store import Store
from tests.test_rubric import GRADE, _store


def _grade_everything(store, tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(
        "marketing_agent.research.tiktok_browser.fetch_video_sync",
        lambda url, out, cdp: Path(out).write_bytes(b"win"),
    )

    def grade(video, meta, model=None):
        g = dict(GRADE)
        if meta.get("label") == "Our clip":
            g.update(movement="slow", sound="music", hurt=["no trending sound"])
        return {
            "grade": g,
            "run": {"model": "m", "latency_s": 1.0, "rubric_version": rubric.RUBRIC_VERSION},
        }

    monkeypatch.setattr(rubric, "grade_video", grade)
    rubric.run(store, "http://cdp", tmp_path / "videos", tmp_path / "renders", log=lambda *a: None)


def test_digest_names_the_shared_traits_and_the_gaps(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    assert rubric.digest(store) == ""  # nothing graded yet
    _grade_everything(store, tmp_path, monkeypatch)
    text = rubric.digest(store)
    assert "The winners share:" in text
    assert "- Movement: fast (100% of them)" in text
    assert "Where our clips keep missing (1 graded):" in text
    assert "- Movement: ours slow, winners fast (1 of 1 clips)" in text
    assert "no trending sound (1x)" in text
    assert "one locked shot (3x)" in text


def test_write_learning_updates_one_entry_in_place(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    assert rubric.write_learning(store, "fitness", "an app") == 0  # nothing to say yet
    _grade_everything(store, tmp_path, monkeypatch)
    lid = rubric.write_learning(store, "fitness", "an app")
    assert lid
    assert rubric.write_learning(store, "fitness", "an app") == lid  # replaced, not duplicated
    es = [e for e in learnings.entries(store, "fitness") if e["title"] == rubric.LEARNING_TITLE]
    assert len(es) == 1 and "The winners share:" in es[0]["body"]


def test_winning_traits_carries_the_digest_and_the_notes(tmp_path, monkeypatch):
    from marketing_agent.campaign import Campaign, Niche
    from marketing_agent.policy import winning_traits

    monkeypatch.setattr(
        "marketing_agent.campaign.load", lambda path=None: Campaign(niche=Niche(name="fitness"))
    )
    store = _store(tmp_path, monkeypatch)
    _grade_everything(store, tmp_path, monkeypatch)
    rubric.write_learning(store, "fitness", "an app")
    learnings.add_rule(store, "fitness", "an app", "Captions match the script word for word.")
    learnings.add(store, "fitness", "an app", "Hooks observation", "Sweaty hooks held viewers.")
    text = winning_traits(store)
    assert "Captions match the script word for word." in text
    assert "What the rubric found" in text
    assert "- Movement: fast (100% of them)" in text
    assert "Recent observations from review" in text
    assert "Hooks observation: Sweaty hooks held viewers." in text
    # the digest is not repeated through the notes
    assert text.count("The winners share:") == 1


def test_notes_text_trims_and_excludes(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    assert learnings.notes_text(store, "fitness") == ""
    learnings.add(store, "fitness", "an app", "Old note", "old " * 300)
    time.sleep(0)
    learnings.add_rule(store, "fitness", "an app", "A rule, not a note.")
    learnings.add(store, "fitness", "an app", "Skip me", "hidden")
    text = learnings.notes_text(store, "fitness", exclude_titles={"Skip me"})
    assert "Old note:" in text and "A rule" not in text and "hidden" not in text
    assert len(text) < 700
