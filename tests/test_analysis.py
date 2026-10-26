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


def test_script_prompt_uses_controlled_findings_only_when_ready(tmp_path):
    from marketing_agent.policy import controlled_traits, winning_traits

    store = Store(tmp_path / "t.sqlite")
    assert controlled_traits(store) == ""
    res = analyze(store)
    res["status"]["reached"]["72h"] = 50
    res["status"]["reached"]["scored"] = 50
    res["status"]["videos"] = 60
    res["fits"]["lift_now"]["pooled"]["hook_type"] = res["fits"]["lift_72h"]["pooled"][
        "hook_type"
    ] = {
        "reference": "text_on_screen",
        "levels": [
            {
                "level": "text_on_screen",
                "reference": True,
                "verdict": "reference",
                "coef": 0,
                "n": 30,
            },
            {
                "level": "pov",
                "reference": False,
                "verdict": "better",
                "coef": 0.41,
                "n": 25,
                "travels": True,
            },
            {"level": "question", "reference": False, "verdict": "thin", "coef": 0.9, "n": 3},
        ],
    }
    save_findings(store, res)
    text = winning_traits(store)
    assert (
        "Controlled for account size" in text
        and "pov +0.41 vs text_on_screen (n=25, travels" in text
    )
    assert "question" not in text


def test_analyze_scores_the_panel_at_cycle_time(tmp_path):
    """The default outcome exists as soon as a panel video is a day old with a view count: its
    lift against niche videos of the same age and account size. Other niches' rows stay out."""
    import time

    from marketing_agent.cohort import build_features
    from tests.test_cohort import _video

    store = Store(tmp_path / "t.sqlite")
    now = int(time.time())
    for i in range(40):
        v = _video(i, f"c{i}", 30 + i, 1000 + 40 * i, 5000)
        v["source_tag"] = "immersiveworkout"
        store.upsert_video(v)
    stale = _video(900, "old", 60, 5000, 5000)
    store.upsert_video(stale)
    with store.conn() as c:
        c.execute("UPDATE videos SET cohort_at=?, niche='fitness' WHERE id!='900'", (now,))
        c.execute("UPDATE videos SET cohort_at=?, niche='wearables' WHERE id='900'", (now,))
    store.set_niche_tags("fitness", ["immersiveworkout"])
    build_features(store)
    res = analyze(store, ["fitness"])
    st = res["status"]
    assert st["videos"] == 40 and st["niches"] == {"fitness": 40}
    assert st["reached"]["scored"] == 40
    assert "lift_now" in res["fits"] and res["outcomes"]["lift_now"].startswith(
        "lift over niche videos"
    )
    assert st["reached"]["scored"] >= res["min_n"]  # enough to stop "collecting" at cycle time
