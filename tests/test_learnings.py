from marketing_agent import learnings
from marketing_agent.store import Store


def test_cycle_entry_on_empty_db_is_honest(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    lid = learnings.write_cycle(store, "fitness", "an app", [{"stage": "run", "status": "ok"}])
    [e] = learnings.entries(store)
    assert e["id"] == lid and e["kind"] == "cycle"
    assert "No videos about the product itself" in e["body"]
    assert "Nothing posted from our account yet" in e["body"]
    assert "First entry." in e["body"] and "All stages ok." in e["body"]


def test_notes_and_document(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    learnings.write_cycle(store, "fitness", "an app")
    learnings.add(store, "fitness", "an app", "Sources are sped up", "Motion 11, not real time.")
    doc = learnings.document(store, "fitness")
    assert doc.index("## Sources are sped up") < doc.index("## Cycle ")
    assert "Motion 11, not real time." in doc
    assert learnings.document(Store(tmp_path / "empty.sqlite")).endswith("writes the first entry.")


def test_second_cycle_reports_changes(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    learnings.write_cycle(store, "fitness", "an app")
    learnings.write_cycle(store, "fitness", "an app")
    first = learnings.entries(store)[0]
    assert "Nothing measurable changed." in first["body"]


def test_cycle_entry_stores_the_numbers_it_draws_from(tmp_path):
    from tests.test_cohort import _video

    store = Store(tmp_path / "db.sqlite")
    store.set_niche_tags("fitness", ["smartring"])
    for i in range(40):
        age = 30 + i
        views = int(10 ** (2.5 + 0.6 * __import__("math").log10(age)) * (1.0 + (i % 3) * 0.6))
        store.upsert_video(_video(i, f"c{i}", age, views, 5000))
        hook = "tutorial" if i % 3 == 2 else "pov"
        store.save_tags(
            str(i),
            "test",
            {"tags": {"hook_type": hook, "visual_style": "ugc_selfie", "pacing_cuts_per_10s": 3}},
        )
    learnings.write_cycle(store, "fitness", "an app")
    [e] = learnings.entries(store)
    f = e["facts"]
    assert f["n_videos"] == 40 and f["n_scored"] == 40 and f["n_tagged"] == 40
    hooks = f["traits"]["hooks"]
    assert hooks[0]["hook_type"] == "tutorial" and hooks[0]["n"] == 13
    assert hooks[0]["mean_reward"] > hooks[1]["mean_reward"]
    assert f["traits"]["pacing"][0]["pacing_bucket"] == "medium"
    assert "### What the data says" in e["body"] and "| tutorial |" in e["body"]
    assert f["own_posts"] == 0 and f["own_mean_lift"] is None


def test_second_cycle_names_the_trait_that_changed(tmp_path):
    from tests.test_cohort import _video

    store = Store(tmp_path / "db.sqlite")
    store.set_niche_tags("fitness", ["smartring"])
    for i in range(40):
        store.upsert_video(_video(i, f"c{i}", 30 + i, 1000 + 400 * (i % 3), 5000))
        store.save_tags(
            str(i), "test", {"tags": {"hook_type": "tutorial" if i % 3 == 2 else "pov"}}
        )
    learnings.write_cycle(store, "fitness", "an app")
    for i in range(40):
        store.save_tags(
            str(i), "test", {"tags": {"hook_type": "pov" if i % 3 == 2 else "tutorial"}}
        )
    learnings.write_cycle(store, "fitness", "an app")
    first = learnings.entries(store)[0]
    assert "best hook type is now pov" in first["body"]
