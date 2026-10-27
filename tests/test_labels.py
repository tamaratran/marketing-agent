"""Our clips are labelled like research videos; the labels ride on the render and move to the
posted video's tags."""

import json
from pathlib import Path

from marketing_agent import labels
from marketing_agent.store import Store


def _seed(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    cid = store.insert(
        "concepts", {"niche": "n", "name": "F", "description": "", "video_ids": "[]"}
    )
    sid = store.insert(
        "scripts",
        {
            "concept_id": cid,
            "hook": "Hi",
            "body": "b",
            "created_at": 1,
            "payload": json.dumps({"sound": "original audio", "duration": 12}),
        },
    )
    clip = tmp_path / "s1_clean.mp4"
    clip.write_bytes(b"x")
    rid = store.insert(
        "renders",
        {
            "script_id": sid,
            "created_at": 1,
            "model": "m",
            "final_path": str(clip),
            "post_path": str(clip),
            "payload": "{}",
        },
    )
    return store, sid, rid


def test_label_render_stores_tags_and_beats_on_the_render(tmp_path, monkeypatch):
    store, sid, rid = _seed(tmp_path)
    seen = {}

    def fake_classify(video, meta, model, transcribe_model, client=None, **kw):
        seen.update(video=Path(video), meta=meta, model=model)
        return {
            "tags": {
                "hook_type": "bold_claim",
                "visual_style": "screen_recording",
                "music_role": "background",
                "pacing_cuts_per_10s": 1.0,
                "product_on_screen_by_5s": True,
                "beats": [{"t_s": 0, "what": "TV shows flappy"}, {"t_s": 4, "what": "she jumps"}],
            },
            "run": {
                "model": model,
                "prompt_version": "v2",
                "transcript": "hi",
                "frame_times": [0, 2],
            },
        }

    monkeypatch.setattr("marketing_agent.classifier.classify.classify", fake_classify)
    assert labels.unlabelled(store) == [rid]
    lab = labels.label_render(store, rid, model="gpt-x")
    assert seen["video"].name == "s1_clean.mp4" and seen["meta"]["desc"] == "Hi"
    assert seen["meta"]["music"] == "original audio" and seen["model"] == "gpt-x"
    assert lab["tags"]["hook_type"] == "bold_claim" and len(lab["tags"]["beats"]) == 2
    stored = json.loads(store.rows("SELECT payload FROM renders WHERE id=?", (rid,))[0]["payload"])
    assert labels.labels_of(stored)["run"]["prompt_version"] == "v2"
    assert labels.unlabelled(store) == [] and labels.unlabelled(store, again=True) == [rid]

    # posting the clip: the video row gets the same labels as tags, once
    assert labels.copy_to_tags(store, "vid1", sid) is True
    tags = json.loads(store.rows("SELECT payload FROM tags WHERE video_id='vid1'")[0]["payload"])
    assert tags["tags"]["visual_style"] == "screen_recording"
    assert labels.copy_to_tags(store, "vid1", sid) is False


def test_no_file_means_no_label(tmp_path):
    store, sid, rid = _seed(tmp_path)
    (tmp_path / "s1_clean.mp4").unlink()
    assert labels.label_render(store, rid) is None
    assert labels.copy_to_tags(store, "vid2", sid) is False
