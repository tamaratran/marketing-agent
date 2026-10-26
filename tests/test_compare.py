from click.testing import CliRunner

from marketing_agent.compare import compare, compare_text
from marketing_agent.own import add_account
from marketing_agent.store import Store
from tests.test_cohort import _video


def _tag(store, vid, hook):
    store.save_tags(vid, "test", {"tags": {"hook_type": hook, "visual_style": "talking_head"}})


def _setup(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    add_account(store, "ourring", "", "ring")
    market = [(1, "bold_claim", 90000), (2, "bold_claim", 70000), (3, "question", 900)]
    market += [(4, "question", 700), (5, "pov", 80000), (6, "pov", 85000)]
    for i, hook, views in market:
        store.upsert_video(_video(i, f"stranger{i}", 100, views))
        _tag(store, str(i), hook)
    for i, hook, views in ((10, "bold_claim", 200), (11, "question", 20000)):
        store.upsert_video(_video(i, "ourring", 100, views))
        _tag(store, str(i), hook)
    return store


def test_compare_lines_up_market_and_ours(tmp_path):
    store = _setup(tmp_path)
    hooks = {r["value"]: r for r in compare(store) if r["trait"] == "hook"}
    assert hooks["bold_claim"]["verdict"] == "works in market, not for us"
    assert hooks["question"]["verdict"] == "works for us, not in market"
    assert hooks["pov"]["verdict"] == "untried by us" and hooks["pov"]["ours_n"] == 0
    assert hooks["bold_claim"]["market_n"] == 2 and hooks["bold_claim"]["ours_n"] == 1
    rows = compare(store)
    assert rows[0]["verdict"] == "works in market, not for us"


def test_compare_reaches_prompt_report_and_cli(tmp_path, monkeypatch):
    from marketing_agent import cli as cli_mod
    from marketing_agent.orchestrator import DailyReport
    from marketing_agent.policy import winning_traits

    store = _setup(tmp_path)
    text = compare_text(store)
    assert "hook bold_claim" in text and "works in market, not for us" in text
    assert text in winning_traits(store)
    report = DailyReport("wearables", "ring").write(tmp_path / "r.md", store).read_text()
    assert "## Ours vs market" in report and "| hook | pov |" in report
    monkeypatch.setattr(cli_mod, "_store", lambda: store)
    out = CliRunner().invoke(cli_mod.cli, ["compare"]).output
    assert "bold_claim" in out and "untried" in out


def test_compare_empty(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    assert compare(store) == [] and compare_text(store) == ""
