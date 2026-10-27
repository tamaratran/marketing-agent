"""Our clips get the same labels as the research videos (hook type, look, sound, pacing, product
by 5s) plus a beat-by-beat breakdown, from the same classifier, so the Clips page and What wins
use the same words. Labels live in renders.payload["labels"]; when the clip is posted they are
copied onto the TikTok video's tags row so the picker and the why panel read them too."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .config import settings
from .store import Store


def labels_of(payload: dict) -> dict | None:
    lab = payload.get("labels")
    return lab if isinstance(lab, dict) and lab.get("tags") else None


def label_render(
    store: Store, render_id: int, model: str | None = None, client=None
) -> dict | None:
    """Classify one render's clean clip and store the result on its payload. None when there is
    no file to watch."""
    from .classifier.classify import classify

    rows = store.rows(
        "SELECT r.id, r.payload, r.post_path, r.final_path, s.hook, s.payload spayload "
        "FROM renders r JOIN scripts s ON s.id=r.script_id WHERE r.id=?",
        (render_id,),
    )
    if not rows:
        return None
    r = rows[0]
    video = next(
        (Path(x) for x in (r["post_path"], r["final_path"]) if x and Path(x).exists()), None
    )
    if video is None:
        return None
    sp = json.loads(r["spayload"] or "{}")
    meta = {
        "desc": r["hook"] or "",
        "music": sp.get("sound") or "",
        "hashtags": [],
        "duration": sp.get("duration"),
    }
    out = classify(
        video, meta, model or settings.openai_model, settings.transcribe_model, client=client
    )
    run = out.get("run") or {}
    labels = {
        "tags": out["tags"],
        "run": {k: run.get(k) for k in ("model", "prompt_version", "transcript", "frame_times")},
        "labelled_at": int(time.time()),
    }
    payload = json.loads(r["payload"] or "{}")
    payload["labels"] = labels
    with store.conn() as c:
        c.execute(
            "UPDATE renders SET payload=? WHERE id=?", (json.dumps(payload, default=str), render_id)
        )
    return labels


def unlabelled(store: Store, again: bool = False) -> list[int]:
    ids = []
    for r in store.rows(
        "SELECT id, payload FROM renders WHERE final_path IS NOT NULL AND model!='stub' ORDER BY id"
    ):
        if again or not labels_of(json.loads(r["payload"] or "{}")):
            ids.append(r["id"])
    return ids


def copy_to_tags(store: Store, video_id: str, script_id: int) -> bool:
    """A posted clip's video row gets the render's labels as its tags, unless already tagged."""
    if store.rows("SELECT 1 FROM tags WHERE video_id=?", (video_id,)):
        return False
    rows = store.rows(
        "SELECT payload FROM renders WHERE script_id=? ORDER BY id DESC LIMIT 1", (script_id,)
    )
    lab = labels_of(json.loads(rows[0]["payload"] or "{}")) if rows else None
    if not lab:
        return False
    store.insert(
        "tags",
        {
            "video_id": video_id,
            "model": (lab.get("run") or {}).get("model") or "render",
            "tagged_at": int(time.time()),
            "payload": json.dumps({"tags": lab["tags"], "run": lab.get("run") or {}}),
        },
    )
    return True
