"""Post-mortems: an underperforming post is compared with its reference videos, and the fixes
become rules for the next scripts."""

import json
import time
from types import SimpleNamespace

from marketing_agent import postmortem
from marketing_agent.learnings import entries, rules
from marketing_agent.store import Store


def _store(tmp_path, monkeypatch):
    monkeypatch.setenv("MKT_DB", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("MKT_DATA_DIR", str(tmp_path))
    from marketing_agent.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return Store(tmp_path / "db.sqlite")


def _posts(monkeypatch, rows):
    monkeypatch.setattr("marketing_agent.own.own_posts", lambda store: rows)


def _post(**kw):
    base = {
        "id": "v1",
        "url": "https://www.tiktok.com/@us/video/v1",
        "script_id": 7,
        "concept_id": None,
        "niche": "fitness",
        "create_time": int(time.time()) - 48 * 3600,
        "lift_matched": -0.6,
        "views_now": 40,
        "desc": "cap",
        "music": "",
        "duration": 12,
    }
    base.update(kw)
    return base


def test_candidates_need_age_script_and_a_low_lift(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    _posts(
        monkeypatch,
        [
            _post(),
            _post(id="young", create_time=int(time.time()) - 3600),
            _post(id="fine", lift_matched=0.2),
            _post(id="noscript", script_id=None),
            _post(id="unknown", lift_matched=None),
        ],
    )
    assert [p["id"] for p in postmortem.candidates(store, "fitness")] == ["v1"]


class FakeClient:
    def __init__(self, verdict):
        self.verdict = verdict
        self.calls = []
        self.responses = SimpleNamespace(parse=self._parse)

    def _parse(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(output_parsed=self.verdict)


def test_run_records_a_learning_and_rules_once(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    _posts(monkeypatch, [_post()])
    monkeypatch.setattr(postmortem, "sources_for", lambda store, post, n=3: [])
    verdict = postmortem.Verdict(
        summary="The TV changes game at 2s and the caption reads like an ad.",
        causes=[
            postmortem.Cause(
                cause="clean clip",
                evidence="frames 2 to 12 show a red runner game, the sources show flappy",
                fix="Pin the TV to the flappy screen for the whole clip.",
            ),
            postmortem.Cause(
                cause="caption",
                evidence="'Transform your cardio' vs the sources' first-person lines",
                fix="Write the caption as the spoken hook, first person, no slogans.",
            ),
        ],
    )
    client = FakeClient(verdict)
    res = postmortem.run(store, "fitness", "P", model="m", client=client)
    assert res == [{"video_id": "v1", "script_id": 7, "learning": res[0]["learning"], "causes": 2}]
    e = [x for x in entries(store, "fitness") if x["kind"] == postmortem.KIND]
    assert len(e) == 1 and e[0]["facts"]["video_id"] == "v1"
    assert e[0]["facts"]["lift_matched"] == -0.6
    assert "red runner" in e[0]["body"]
    assert rules(store, "fitness") == [
        "Pin the TV to the flappy screen for the whole clip.",
        "Write the caption as the spoken hook, first person, no slogans.",
    ]
    user = client.calls[0]["input"][1]["content"]
    assert "Checklist" in user[0]["text"] and "OUR CLIP" in user[1]["text"]
    # second cycle: already examined, nothing re-judged
    assert postmortem.run(store, "fitness", "P", model="m", client=client) == []
    assert len(client.calls) == 1
    assert len(postmortem.run(store, "fitness", "P", model="m", client=client, again=True)) == 1


def test_no_causes_means_no_rules(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    _posts(monkeypatch, [_post()])
    monkeypatch.setattr(postmortem, "sources_for", lambda store, post, n=3: [])
    client = FakeClient(postmortem.Verdict(summary="Matches the sources.", causes=[]))
    postmortem.run(store, "fitness", "P", model="m", client=client)
    assert rules(store, "fitness") == []
    e = [x for x in entries(store, "fitness") if x["kind"] == postmortem.KIND][0]
    assert "no fix from this post" in e["body"]
    assert json.loads(json.dumps(e["facts"]))["causes"] == []
