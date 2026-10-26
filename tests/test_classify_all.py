import math

from click.testing import CliRunner

from marketing_agent import cli
from marketing_agent.scoreboard import TRAIT_MIN_N, build
from marketing_agent.store import Store
from tests.test_cohort import _video


def _panel(store: Store, n: int, tagged: int, hook_of=lambda i: "pov") -> None:
    store.set_niche_tags("fitness", ["smartring"])
    for i in range(n):
        age = 30 + i
        views = int(10 ** (2.5 + 0.6 * math.log10(age)) * (1.0 + (i % 3) * 0.6))
        store.upsert_video(_video(i, f"c{i}", age, views, 5000))
        if i < tagged:
            store.save_tags(
                str(i),
                "test",
                {"tags": {"hook_type": hook_of(i), "visual_style": "ugc_selfie"}},
            )


def test_trait_rows_need_min_n_videos(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    # 12 tagged: 4 "tutorial" (withheld), 8 "pov" (shown)
    _panel(store, 20, 12, hook_of=lambda i: "tutorial" if i % 3 == 0 else "pov")
    sb = build(store, tags=["smartring"])
    assert sb["trait_min_n"] == TRAIT_MIN_N == 5
    assert [r["hook_type"] for r in sb["hooks"]] == ["pov"]
    assert sb["hooks"][0]["n"] == 8
    assert sb["n_tagged"] == 12  # the count still says how many are classified


def test_panel_untagged_defaults_to_every_scored_video(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    _panel(store, 30, 7)
    rows = cli.panel_untagged(store, "fitness")
    assert len(rows) == 23 and all(not r.get("hook_type") for r in rows)
    assert len(cli.panel_untagged(store, "fitness", limit=5)) == 5
    # newest first, so a cycle's fresh videos are done before the backlog
    assert [r["create_time"] for r in rows] == sorted(
        (r["create_time"] for r in rows), reverse=True
    )


def test_daily_classify_panel_default_is_uncapped():
    opt = next(p for p in cli.daily.params if p.name == "classify_panel")
    assert opt.default is None
    opt = next(p for p in cli.classify.params if p.name == "limit")
    assert opt.default is None
    assert CliRunner().invoke(cli.cli, ["daily", "--help"]).exit_code == 0
