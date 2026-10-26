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
