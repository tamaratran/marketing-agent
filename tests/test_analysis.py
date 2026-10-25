import random

from marketing_agent.analysis import CONTROLS, analyze, controlled_lift, ols, save_findings
from marketing_agent.store import Store


def _rows(n=300, seed=1):
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        fb = rng.choice(["1k-10k", "10k-100k"])
        hook = "pov" if rng.random() < (0.7 if fb == "10k-100k" else 0.3) else "text_on_screen"
        lift = 0.4 * (hook == "pov") + 0.6 * (fb == "10k-100k") + rng.gauss(0, 0.3)
        rows.append(
            {
                "hook_type": hook,
                "follower_bucket": fb,
                "niche": "wearables",
                "duration_bucket": "10-20s",
                "posted_hour_bucket": "morning",
                "lift_72h": lift,
            }
        )
    return rows


def test_ols_removes_the_follower_confound():
    rows = _rows()
    fit = ols(rows, "lift_72h", "hook_type", CONTROLS)
    pov = next(lv for lv in fit["levels"] if lv["level"] == "pov")
    raw_gap = pov["raw_mean"] - next(lv for lv in fit["levels"] if lv["reference"])["raw_mean"]
    assert raw_gap > 0.6  # confounded: pov accounts are bigger
    assert 0.3 < pov["coef"] < 0.6 and pov["verdict"] == "better"


def test_thin_cells_and_no_evidence_are_labelled():
    rows = _rows(30)
    fit = ols(rows, "lift_72h", "hook_type", CONTROLS)
    assert all(lv["verdict"] in ("thin", "reference") for lv in fit["levels"])
    rng = random.Random(3)
    noise = [dict(r, lift_72h=rng.gauss(0, 1)) for r in _rows(400, 2)]
    fit = ols(noise, "lift_72h", "hook_type", CONTROLS)
    assert next(lv for lv in fit["levels"] if not lv["reference"])["verdict"] in (
        "no evidence",
        "better",
        "worse",
    )


def test_analyze_reports_collecting_and_roundtrips(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    res = analyze(store)
    assert res["status"]["videos"] == 0 and res["fits"]["lift_72h"]["pooled"]
    save_findings(store, res)
    assert controlled_lift(store, "hook_type") == {}
