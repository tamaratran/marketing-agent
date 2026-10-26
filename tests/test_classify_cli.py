from pathlib import Path

from click.testing import CliRunner

from marketing_agent import cli as cli_mod
from marketing_agent.classifier import classify as classify_mod
from marketing_agent.research import tiktok_browser
from marketing_agent.store import Store


def _video(vid: str) -> dict:
    item = {"id": vid, "createTime": "1", "desc": "", "author": {"uniqueId": "a"}, "stats": {}}
    return tiktok_browser._row(item, "fitness")


def test_classify_refetches_missing_local_file_and_skips_unfetchable(tmp_path: Path, monkeypatch):
    store = Store(tmp_path / "db.sqlite")
    for vid in ("1", "2"):
        store.upsert_video(_video(vid))
        store.set_local_path(vid, f"data/videos/{vid}.mp4")
    monkeypatch.setattr(cli_mod, "_store", lambda: store)
    monkeypatch.setattr(cli_mod.settings, "data_dir", tmp_path)

    def fake_fetch(url, out, cdp):
        if url.endswith("/2"):
            raise RuntimeError("gone")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"mp4")

    seen = []

    def fake_classify(path, v, model, transcribe_model):
        seen.append(Path(path))
        return {
            "run": {"latency_s": 0},
            "tags": {
                "hook_type": "pov",
                "visual_style": "ugc",
                "demo_score_1_5": 3,
                "concept": "c",
            },
        }

    monkeypatch.setattr(tiktok_browser, "fetch_video_sync", fake_fetch)
    monkeypatch.setattr(classify_mod, "classify", fake_classify)
    monkeypatch.setattr(store, "save_tags", lambda vid, model, res: None)
    res = CliRunner().invoke(cli_mod.cli, ["classify"])
    assert res.exit_code == 0, res.output
    assert seen == [tmp_path / "videos" / "1.mp4"]
    assert store.rows("SELECT local_path FROM videos WHERE id='1'")[0]["local_path"] == str(
        tmp_path / "videos" / "1.mp4"
    )
