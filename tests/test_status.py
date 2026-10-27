import json

from fastapi.testclient import TestClient

from marketing_agent import status

NOW = 1_800_000_000


def _get(data):
    return lambda path: data.get(path.split("?")[0])


def _data():
    return {
        "/campaign": {
            "account": {"handle": "kriscaroll"},
            "niche": {"name": "fitness"},
            "product": {"name": "Immersive Workout"},
            "cycle": {"clips": 5, "resolution": "720p"},
        },
        "/ours": {
            "accounts": [{"handle": "kriscaroll"}],
            "posts": [
                {
                    "id": "1",
                    "url": "https://t/1",
                    "script_id": 95,
                    "hook": "POV: cardio got fun",
                    "create_time": NOW - 20 * 3600,
                    "age_h": 20.0,
                    "views_now": 302,
                    "lift_now": -0.3,
                    "lift_72h": None,
                    "followers": 289,
                },
                {
                    "id": "2",
                    "url": "https://t/2",
                    "script_id": 90,
                    "hook": "old one",
                    "create_time": NOW - 100 * 3600,
                    "age_h": 100.0,
                    "views_now": 5000,
                    "lift_now": 0.1,
                    "lift_72h": 0.28,
                    "followers": 289,
                },
            ],
            "rewards": {},
        },
        "/scripts": [
            {
                "id": 141,
                "concept": "List",
                "hook": "6 moves",
                "created_at": NOW - 60,
                "demo_score": 5,
                "why": {"expected_lift": -0.018},
            },
            {
                "id": 139,
                "concept": "Challenge",
                "hook": "Flappy",
                "created_at": NOW - 120,
                "demo_score": 5,
                "why": {"expected_lift": 0.08},
            },
            {
                "id": 80,
                "concept": "Old",
                "hook": "stale",
                "created_at": NOW - 3 * 86400,
                "demo_score": 3,
                "why": {"expected_lift": 0.5},
            },
        ],
        "/renders": [
            {
                "id": 1,
                "script_id": 95,
                "hook": "POV: cardio got fun",
                "post_path": "x",
                "post_text": ["POV"],
                "post_session_url": None,
                "post_requested_at": None,
                "post_attempts": 0,
                "hold_reason": None,
            },
            {
                "id": 2,
                "script_id": 139,
                "hook": "Flappy",
                "post_path": "x",
                "post_text": ["Flappy"],
                "post_session_url": "https://d/s",
                "post_requested_at": NOW - 600,
                "post_attempts": 0,
                "hold_reason": None,
            },
            {
                "id": 3,
                "script_id": 141,
                "hook": "6 moves",
                "post_path": "x",
                "post_text": [],
                "post_session_url": "https://d/s",
                "post_requested_at": NOW - 2 * 3600,
                "post_attempts": 4,
                "hold_reason": None,
            },
            {
                "id": 4,
                "script_id": 138,
                "hook": "held",
                "post_path": "x",
                "post_text": [],
                "post_session_url": None,
                "post_requested_at": None,
                "post_attempts": 0,
                "hold_reason": "TV wrong",
            },
            {
                "id": 5,
                "script_id": 83,
                "hook": "no clean",
                "post_path": None,
                "post_text": [],
                "post_session_url": None,
                "post_requested_at": None,
                "post_attempts": 0,
                "hold_reason": None,
            },
        ],
        "/runs": [
            {
                "id": 9,
                "created_at": NOW - 600,
                "finished_at": None,
                "note": "cycle",
                "url": "https://d/r",
            },
            {
                "id": 8,
                "created_at": NOW - 300,
                "finished_at": None,
                "note": "post s139 from @kriscaroll",
            },
            {"id": 7, "created_at": NOW - 5 * 3600, "finished_at": None, "note": "cycle"},
        ],
        "/learnings": [
            {
                "id": 1,
                "kind": "cycle",
                "created_at": NOW - 3600,
                "facts": {
                    "n_scored": 220,
                    "n_tagged": 248,
                    "traits": {
                        "styles": [
                            {"visual_style": "screen_recording", "n": 74, "mean_reward": 0.28},
                            {"visual_style": "animation", "n": 5, "mean_reward": -0.55},
                        ],
                        "pacing": [{"pacing_bucket": "slow", "n": 150, "mean_reward": 0.06}],
                    },
                },
            },
            {
                "id": 2,
                "kind": "rule",
                "created_at": NOW - 100,
                "title": "TV rule",
                "body": "The TV shows only our game.",
            },
            {
                "id": 3,
                "kind": "note",
                "created_at": NOW - 50,
                "title": "First post is up",
                "body": "...",
            },
        ],
        "/findings": {"min_n": 20},
    }


def test_pct_reads_like_the_site():
    assert status.pct(0.28) == "+91%"
    assert status.pct(-0.3) == "-50%"
    assert status.pct(0.0) == "same"
    assert status.pct(0.6) == "4.0x"
    assert status.pct(None) == "no data"


def test_build_joins_posts_clips_scripts_and_learnings():
    st = status.build(_get(_data()), now=NOW)
    assert st["account"] == {"handle": "kriscaroll", "followers": 289}

    by_script = {c["script_id"]: c for c in st["clips"]}
    assert by_script[95]["status"] == "posted" and by_script[95]["post_url"] == "https://t/1"
    assert by_script[95]["views_now"] == 302
    assert by_script[139]["status"] == "posting"
    assert by_script[141]["status"] == "ready"  # stale hand-off, attempts used up: back to ready
    assert by_script[138]["status"] == "on hold"
    assert by_script[83]["status"] == "rendered" and by_script[83]["clean_url"] is None
    assert by_script[95]["clean_url"].endswith("/s95_clean.mp4")
    assert by_script[95]["poster_url"].endswith("/s95.jpg")

    posts = {p["script_id"]: p for p in st["posts"]}
    assert posts[95]["status"] == "too early"
    assert posts[90]["status"] == "scored" and posts[90]["lift_72h_text"] == "+91%"

    assert [s["id"] for s in st["proposed_scripts"]] == [139, 141]  # the old batch is left out
    assert st["proposed_scripts"][0]["rendered"] is True

    L = st["learnings"]
    assert L["n_scored"] == 220 and L["min_n"] == 20
    assert L["best_bets"][0] == {
        "trait": "visual_style",
        "value": "screen_recording",
        "lift": 0.28,
        "lift_text": "+91%",
        "n": 74,
    }
    assert [b["trait"] for b in L["best_bets"]] == ["visual_style", "pacing_bucket"]
    assert [e["title"] for e in L["rules"]] == ["TV rule"]
    assert [e["title"] for e in L["notes"]] == ["First post is up"]

    assert (
        st["running"]["id"] == 9
    )  # the 5h-old unfinished run is stale, the poster run is not a cycle
    assert [r["id"] for r in st["posting"]] == [8]
    json.dumps(st)


def test_render_is_plain_markdown():
    md = status.render(status.build(_get(_data()), now=NOW))
    assert md.startswith("# Immersive Workout on TikTok (@kriscaroll, 289 followers)")
    assert "A run is going" in md and "Posting now: s139" in md
    assert (
        '- s95 "POV: cardio got fun": 302 views, 20h old, -50% vs videos like it so far. https://t/1'
        in md
    )
    assert '- s90 "old one": 5,000 views, 4d old, +91% vs the account\'s usual at 72h.' in md
    assert '- s138 "held": on hold; held: TV wrong.' in md
    assert '- s139 "Flappy" (Challenge, +20% expected, rendered)' in md
    assert (
        "Best bets: visual_style screen_recording +91% (74 videos); pacing_bucket slow +15% (150 videos)"
        in md
    )
    assert "- visual_style: screen_recording +91% (74), animation -72% (5)" in md
    assert "- The TV shows only our game." in md


def test_build_against_an_empty_api(tmp_path, monkeypatch):
    from marketing_agent import api
    from marketing_agent.store import Store

    monkeypatch.setattr(api, "_store", lambda: Store(tmp_path / "db.sqlite"))
    client = TestClient(api.app)
    st = status.build(lambda p: client.get(p).json(), now=NOW)
    assert st["posts"] == [] and st["clips"] == [] and st["proposed_scripts"] == []
    assert st["learnings"]["best_bets"] == [] and st["running"] is None
    md = status.render(st)
    assert "None yet." in md and "None rendered yet." in md


def test_cli_status_json_and_markdown(monkeypatch):
    from click.testing import CliRunner

    from marketing_agent import cli as cli_mod

    data = _data()

    class R:
        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self.body

    import httpx

    monkeypatch.setenv("MKT_API_URL", "https://api.test")
    monkeypatch.setattr(
        httpx,
        "get",
        lambda url, **kw: R(data.get(url.replace("https://api.test", "").split("?")[0])),
    )
    res = CliRunner().invoke(cli_mod.cli, ["status", "--json"])
    assert res.exit_code == 0, res.output
    st = json.loads(res.output)
    assert st["api"] == "https://api.test" and len(st["clips"]) == 5
    res = CliRunner().invoke(cli_mod.cli, ["status"])
    assert res.exit_code == 0, res.output
    assert res.output.startswith("# Immersive Workout on TikTok")
