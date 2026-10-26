"""The script batch spans the picker's top formats, each script stored with why its format was
proposed, and scripts rank by expected lift before the writer's demo score."""

import json
import time

import marketing_agent.video.scripts as scripts_mod
from marketing_agent.policy import propose_batch, rank_scripts
from marketing_agent.store import Store
from marketing_agent.video.scripts import write_scripts
from tests.test_format import _FakeClient, _Parsed
from tests.test_policy_traits import _concept, _post, _tag, _world


def _formats(store):
    for i in range(1, 7):
        _tag(store, str(100 + i), hook="pov")
    ids = [_concept(store, f"F{i}", [str(100 + i)], early=100 + 50 * i) for i in range(1, 6)]
    ids.append(_concept(store, "Clone", ["106"], early=10, kind="format"))
    return ids


def test_batch_spans_three_formats_by_pick_share_with_reasons(tmp_path):
    store = _world(tmp_path)
    ids = _formats(store)
    _post(store, ids[0], "801", views=10, age_h=48)
    batch = propose_batch(store, "wearables", formats=3)
    assert len(batch) == 3 and len({c["name"] for c in batch}) == 3
    assert batch[0]["kind"] == "format", "the clone leads by pick share"
    assert batch[0]["pick_share"] >= batch[1]["pick_share"] >= batch[2]["pick_share"]
    assert "F1" not in {c["name"] for c in batch}, "the flop drops out of the top three"
    why = batch[0]["why"]
    assert set(why) >= {"pick_share", "head_start", "expected_lift", "own_n", "traits", "kind"}
    assert why["pick_share"] == batch[0]["pick_share"] and why["head_start"] == batch[0]["prior"]
    assert isinstance(why["traits"], list)


def test_propose_batch_on_empty_niche_is_empty(tmp_path):
    assert propose_batch(Store(tmp_path / "e.sqlite"), "wearables") == []


class _ThreeScripts(_FakeClient):
    def parse(self, model, input, text_format):
        mk = lambda hook, demo: scripts_mod.Script(  # noqa: E731
            hook=hook,
            body="b",
            captions=["c"],
            product_reveal_s=2,
            demo_score_1_5=demo,
            why="",
            video_prompt="p",
            spoken=hook,
            hook_on_screen=True,
            sound="",
        )
        return _Parsed([mk("weak", 2), mk("best", 5), mk("ok", 4)])


def test_write_scripts_keeps_the_best_and_stores_why(tmp_path, monkeypatch):
    monkeypatch.setattr(scripts_mod, "OpenAI", _ThreeScripts)
    store = Store(tmp_path / "db.sqlite")
    why = {"pick_share": 0.5, "expected_lift": 0.2}
    out = write_scripts(
        store, {"id": 1, "name": "F", "description": "d"}, "P", n=3, keep=2, why=why
    )
    assert [s["hook"] for s in out] == ["best", "ok"]
    rows = store.rows("SELECT hook, payload FROM scripts ORDER BY id")
    assert [r["hook"] for r in rows] == ["best", "ok"]
    assert json.loads(rows[0]["payload"])["why"] == why


def test_rank_scripts_by_expected_lift_then_demo(tmp_path):
    rows = [
        {"id": 1, "demo_score": 5, "payload": json.dumps({"why": {"expected_lift": 0.0}})},
        {"id": 2, "demo_score": 3, "payload": json.dumps({"why": {"expected_lift": 0.4}})},
        {"id": 3, "demo_score": 4, "payload": "{}"},
        {"id": 4, "demo_score": 5, "why": {"expected_lift": 0.4}},
    ]
    assert [r["id"] for r in rank_scripts(rows)] == [4, 2, 1, 3]


def test_scripts_api_returns_why(tmp_path, monkeypatch):
    monkeypatch.setenv("MKT_DB", str(tmp_path / "db.sqlite"))
    from fastapi.testclient import TestClient

    from marketing_agent import api

    client = TestClient(api.app)
    store = api._store()
    cid = store.insert(
        "concepts",
        {
            "niche": "fitness",
            "name": "F",
            "description": "",
            "video_ids": "[]",
            "early_score": 1,
            "created_at": int(time.time()),
            "payload": "{}",
        },
    )
    store.insert(
        "scripts",
        {
            "concept_id": cid,
            "product": "P",
            "created_at": int(time.time()),
            "hook": "h",
            "body": "",
            "demo_score": 4,
            "payload": json.dumps({"why": {"pick_share": 0.3, "expected_lift": 0.1}}),
        },
    )
    rows = client.get("/scripts?niche=fitness").json()
    assert rows, api._store().path if hasattr(api._store(), "path") else str(api.settings.db_path)
    assert rows[0]["why"] == {"pick_share": 0.3, "expected_lift": 0.1}
