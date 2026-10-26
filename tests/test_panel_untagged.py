from marketing_agent.cli import panel_untagged
from marketing_agent.store import Store
from tests.test_cohort import _video


def test_panel_untagged_is_scored_untagged_niche_videos_newest_first(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    store.set_niche_tags("fitness", ["smartring"])
    for i in range(40):
        store.upsert_video(_video(i, f"c{i}", 30 + i, 1000 + 10 * i, 5000))
    store.upsert_video(_video(100, "young", 3, 50, 5000))  # too young for a score
    other = _video(101, "other", 40, 500, 5000)
    other["source_tag"] = "cooking"
    store.upsert_video(other)
    store.save_tags("0", "test", {"tags": {"hook_type": "pov"}})
    rows = panel_untagged(store, "fitness", 5)
    ids = [r["id"] for r in rows]
    assert ids == ["1", "2", "3", "4", "5"]
    assert "0" not in ids and "100" not in ids and "101" not in ids
    assert len(panel_untagged(store, "fitness", 100)) == 39
