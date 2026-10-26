import time

from click.testing import CliRunner

from marketing_agent.cohort import build_features, enroll, features
from marketing_agent.creators.ops import add_creator, record_post
from marketing_agent.own import add_account
from marketing_agent.research.radar import rank
from marketing_agent.scoreboard import build
from marketing_agent.store import Store
from tests.test_cohort import _video


def _setup(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    add_account(store, "ourring", "", "ring")
    for i in range(1, 4):
        store.upsert_video(_video(i, f"stranger{i}", 2, 50000))
    store.upsert_video(_video(10, "ourring", 500, 800))  # our account, before registration
    store.upsert_video(_video(11, "ourring", 2, 3000))  # our campaign post
    with store.conn() as c:
        c.execute("UPDATE videos SET ours=1, cohort_at=? WHERE id='11'", (int(time.time()),))
    add_creator(store, "amy", "discord", 1.0)
    record_post(
        store, "amy", "https://www.tiktok.com/@amy/video/12", stats=_video(12, "amy", 2, 9000)
    )
    return store


def test_reference_and_ours_never_mix(tmp_path):
    store = _setup(tmp_path)
    ref = {r["id"] for r in store.latest(group="reference")}
    ours = {r["id"] for r in store.latest(group="ours")}
    assert ref == {"1", "2", "3"}
    assert ours == {"10", "11", "12"}
    assert {r["id"] for r in store.latest()} == ref | ours
    assert {r["id"] for r in rank(store)} == ref
    assert {r["id"] for r in build(store)["videos"]} == ref
    assert {r["id"] for r in build(store, group="ours")["videos"]} == ours


def test_cohort_panel_is_reference_only(tmp_path):
    store = _setup(tmp_path)
    rows = store.latest()
    got = enroll(store, "wearables", rows)
    assert {r["id"] for r in got} == {"1", "2", "3"}
    build_features(store)
    assert {f["video_id"] for f in features(store, group="reference")} == {"1", "2", "3"}
    assert "11" in {f["video_id"] for f in features(store)}  # still followed for repoll


def test_prompt_and_cli_label_each_group(tmp_path, monkeypatch):
    from marketing_agent import cli as cli_mod
    from marketing_agent.policy import winning_traits

    store = _setup(tmp_path)
    assert "Our own posts" not in winning_traits(store)  # nothing old enough to score yet
    monkeypatch.setattr(cli_mod, "_store", lambda: store)
    out = CliRunner().invoke(cli_mod.cli, ["scoreboard"]).output
    assert "Our posts: 3 videos" in out and "Reference videos (research): 3 videos" in out
