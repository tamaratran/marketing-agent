from marketing_agent.dashboard import render
from marketing_agent.store import Store


def test_dashboard_renders_on_empty_store(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    out = render(store, "wearables", tmp_path / "site" / "index.html")
    text = out.read_text()
    assert "<!doctype html>" in text and "marketing agent · wearables" in text
    assert "no clips yet" in text and "none yet" in text


def test_dashboard_copies_clips_and_links_them(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    clip = tmp_path / "s1.mp4"
    clip.write_bytes(b"fake")
    with store.conn() as c:
        c.execute(
            "INSERT INTO scripts (id, concept_id, product, created_at, hook, body, demo_score, payload)"
            " VALUES (1, NULL, 'p', 1, 'hook text', '', 5, '{}')"
        )
        c.execute(
            "INSERT INTO renders (script_id, created_at, model, prompt, raw_path, final_path, cost_usd, payload)"
            f" VALUES (1, 1, 'm', '', '', '{clip}', 2.5, '{{}}')"
        )
    out = render(store, "wearables", tmp_path / "site" / "index.html")
    assert (tmp_path / "site" / "renders" / "s1.mp4").read_bytes() == b"fake"
    text = out.read_text()
    assert 'src="renders/s1.mp4"' in text and "hook text" in text and "$2.50" in text
