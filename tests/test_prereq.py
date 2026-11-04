from pathlib import Path

import pytest

from marketing_agent import learnings, prereq, rubric
from marketing_agent.store import Store

GRADE = {
    "content": "a woman playing the game on the TV",
    "gender": "woman",
    "build": "slim",
    "movement": "moderate",
    "sound": "game",
    "hurt": [],
    "helped": ["cuts on the beat"],
}


def _store(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    with store.conn() as c:
        c.execute(
            "INSERT INTO videos (id, url, author) VALUES ('1', 'https://t/v/1', 'a'), "
            "('2', 'https://t/v/2', 'b')"
        )
        c.execute("INSERT INTO scripts (id, hook) VALUES (5, 'burn 400 calories')")
    return store


def _run_that_grades(ours_build="athletic"):
    def run(store, cdp, videos_dir, renders_dir, video_ids=None, log=print, **kw):
        for vid in video_ids or []:
            rubric.save(
                store,
                rubric.WINNER,
                {
                    "grade": dict(GRADE),
                    "run": {"model": "m", "rubric_version": rubric.RUBRIC_VERSION},
                },
                video_id=vid,
            )
        rubric.save(
            store,
            rubric.OURS,
            {
                "grade": {**GRADE, "build": ours_build, "hurt": ["no sweat", "hoodie"]},
                "run": {"model": "m", "rubric_version": rubric.RUBRIC_VERSION},
            },
            script_id=5,
        )
        return {"winners": len(video_ids or []), "ours": 1, "failed": [], "concept": None}

    return run


def test_before_scripts_grades_writes_the_learnings_and_reads_them_back(tmp_path, monkeypatch):
    store = _store(tmp_path)
    learnings.add_rule(store, "fit", "the app", "Never write the app name on screen.")
    monkeypatch.setattr(rubric, "grade_video", lambda *a, **k: pytest.fail("not called"))
    monkeypatch.setattr(rubric, "run", _run_that_grades())
    logs = []
    text = prereq.before_scripts(
        store,
        niche="fit",
        product="the app",
        winner_ids=["1", "2"],
        cdp_url="http://cdp",
        videos_dir=tmp_path / "v",
        renders_dir=tmp_path / "r",
        log=logs.append,
    )
    notes = [e for e in learnings.entries(store, "fit") if e["kind"] == learnings.NOTE]
    assert len(notes) == 1 and notes[0]["title"].startswith(prereq.NOTE_PREFIX)
    body = notes[0]["body"]
    assert "2 winners" in body and "s5" in body and "athletic" in body and "no sweat" in body
    # the writer gets the rule and the fresh note
    assert "Never write the app name on screen." in text and notes[0]["title"] in text
    assert any("rubric note written" in line for line in logs)

    # the same finding is not written twice
    prereq.before_scripts(
        store,
        niche="fit",
        product="the app",
        winner_ids=["1", "2"],
        cdp_url="http://cdp",
        videos_dir=tmp_path / "v",
        renders_dir=tmp_path / "r",
        log=logs.append,
    )
    assert len([e for e in learnings.entries(store, "fit") if e["kind"] == learnings.NOTE]) == 1
    assert any("unchanged" in line for line in logs)

    # a changed finding is
    monkeypatch.setattr(rubric, "run", _run_that_grades(ours_build="slim"))
    prereq.before_scripts(
        store,
        niche="fit",
        product="the app",
        winner_ids=["1", "2"],
        cdp_url="http://cdp",
        videos_dir=tmp_path / "v",
        renders_dir=tmp_path / "r",
        log=logs.append,
    )
    assert len([e for e in learnings.entries(store, "fit") if e["kind"] == learnings.NOTE]) == 2


def test_before_scripts_refuses_without_graded_winners(tmp_path, monkeypatch):
    store = _store(tmp_path)

    def run(store, cdp, videos_dir, renders_dir, video_ids=None, log=print, **kw):
        return {"winners": 0, "ours": 0, "failed": ["1: timeout"], "concept": None}

    monkeypatch.setattr(rubric, "run", run)
    with pytest.raises(prereq.NotReady, match="no winner has a grade: 1: timeout"):
        prereq.before_scripts(
            store,
            niche="fit",
            product="the app",
            winner_ids=["1"],
            cdp_url="http://cdp",
            videos_dir=tmp_path / "v",
            renders_dir=tmp_path / "r",
            log=lambda *a: None,
        )
    assert learnings.entries(store, "fit") == []

    # one of two named winners graded is still not enough
    def half(store, cdp, videos_dir, renders_dir, video_ids=None, log=print, **kw):
        rubric.save(
            store,
            rubric.WINNER,
            {"grade": dict(GRADE), "run": {"model": "m", "rubric_version": rubric.RUBRIC_VERSION}},
            video_id="1",
        )
        return {"winners": 1, "ours": 0, "failed": ["2: blocked"], "concept": None}

    monkeypatch.setattr(rubric, "run", half)
    with pytest.raises(prereq.NotReady, match="winners not graded: 2; failures: 2: blocked"):
        prereq.before_scripts(
            store,
            niche="fit",
            product="the app",
            winner_ids=["1", "2"],
            cdp_url="http://cdp",
            videos_dir=tmp_path / "v",
            renders_dir=tmp_path / "r",
            log=lambda *a: None,
        )


def test_run_takes_our_api_copy_before_the_browser(tmp_path, monkeypatch):
    class R:
        status_code = 200
        content = b"ftyp moov"

    monkeypatch.setattr("httpx.get", lambda *a, **k: R())
    out = tmp_path / "1.mp4"
    assert rubric._from_api("1", out) and out.read_bytes() == b"ftyp moov"

    class Bad:
        status_code = 404
        content = b""

    monkeypatch.setattr("httpx.get", lambda *a, **k: Bad())
    assert not rubric._from_api("2", tmp_path / "2.mp4") and not (tmp_path / "2.mp4").exists()
    assert Path(out).exists()
