"""Run modes: research (no renders), render (latest batch only), full (unchanged)."""

from marketing_agent.orchestrator import daily_prompt


def test_research_mode_renders_nothing():
    p = daily_prompt("fitness", ["a"], "P", renders=5, mode="research")
    assert "--renders 0" in p and "mkt daily" in p


def test_render_mode_only_renders_latest_batch():
    p = daily_prompt(
        "fitness", ["a"], "P", renders=3, resolution="480p", refs=["x.png"], mode="render"
    )
    assert "mkt render-latest --renders 3 --resolution 480p" in p and '--ref "x.png"' in p
    assert "mkt daily" not in p and "mkt stage render" in p and "Never post" in p


def test_full_mode_unchanged():
    p = daily_prompt("fitness", ["a"], "P", renders=5)
    assert "mkt daily fitness a" in p and "--renders 5" in p


def test_render_mode_posts_each_kept_clip():
    p = daily_prompt("fitness", ["a"], "P", renders=2, mode="render", api_url="https://api.example")
    assert "POST https://api.example/renders/<script_id>/post" in p and "never for a held clip" in p
