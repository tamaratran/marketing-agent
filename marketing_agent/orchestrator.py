"""Hands the daily loop to a Devin session through the Devin API, and writes the report that
session (or a human) reads afterwards.

`mkt daily` is the deterministic part: every stage in order, failures recorded instead of raised,
one markdown report at the end. The Devin session is the judgment part: it runs `mkt daily`, reads
the report, fixes a stage that broke, pushes the state branch and summarises the cycle."""

import os
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .store import Store

API_URL = os.environ.get("DEVIN_API_URL", "https://api.devin.ai/v3")
DEFAULT_REPO = os.environ.get("MKT_REPO", "tamaratran/marketing-agent")
STATE_BRANCH = os.environ.get("MKT_STATE_BRANCH", "state")
SETTLED = {"exit", "error", "suspended"}
SETTLED_DETAIL = {"finished", "waiting_for_user", "waiting_for_approval"}


class DevinClient:
    """Thin client for the v3 sessions API. Auth is a personal access token or service-user key
    in DEVIN_API_KEY; the org id (org-...) comes from DEVIN_ORG_ID."""

    def __init__(
        self,
        api_key: str | None = None,
        org_id: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        api_key = api_key or os.environ.get("DEVIN_API_KEY")
        org_id = org_id or os.environ.get("DEVIN_ORG_ID")
        if not api_key:
            raise RuntimeError("DEVIN_API_KEY not set (Settings > Devin API > PATs)")
        if not org_id:
            raise RuntimeError("DEVIN_ORG_ID not set (top of Settings > Devin API)")
        self.org_id = org_id
        self.http = httpx.Client(
            base_url=f"{API_URL}/organizations/{org_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60,
            transport=transport,
        )

    def _json(self, r: httpx.Response) -> dict:
        if r.status_code >= 400:
            raise RuntimeError(f"Devin API {r.status_code}: {r.text[:300]}")
        return r.json()

    def create_session(
        self,
        prompt: str,
        title: str | None = None,
        tags: list[str] | None = None,
        repos: list[str] | None = None,
        max_acu_limit: int | None = None,
        devin_mode: str | None = None,
    ) -> dict:
        body = {"prompt": prompt, "title": title, "tags": tags, "repos": repos}
        if max_acu_limit:
            body["max_acu_limit"] = max_acu_limit
        if devin_mode:
            body["devin_mode"] = devin_mode
        body = {k: v for k, v in body.items() if v is not None}
        return self._json(self.http.post("/sessions", json=body))

    def get_session(self, session_id: str) -> dict:
        return self._json(self.http.get(f"/sessions/{session_id}"))

    def send_message(self, session_id: str, message: str) -> dict:
        return self._json(
            self.http.post(f"/sessions/{session_id}/messages", json={"message": message})
        )

    def wait(self, session_id: str, timeout_s: int = 3 * 3600, poll_s: int = 60) -> dict:
        """Poll until the session finishes, blocks on a question, or dies."""
        t0 = time.time()
        while True:
            s = self.get_session(session_id)
            if s.get("status") in SETTLED or s.get("status_detail") in SETTLED_DETAIL:
                return s
            if time.time() - t0 > timeout_s:
                return s
            time.sleep(poll_s)


def daily_prompt(
    niche: str,
    tags: list[str],
    product: str,
    renders: int = 1,
    resolution: str = "720p",
    repo: str = DEFAULT_REPO,
    state_branch: str = STATE_BRANCH,
    refs: list[str] | None = None,
    product_tags: list[str] | None = None,
) -> str:
    """What the Devin session is told. Self-contained: the session starts with no history."""
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    tag_str = " ".join(tags)
    ref_str = "".join(f' --ref "{r}"' for r in refs or [])
    ref_str += "".join(f' --product-tag "{t}"' for t in product_tags or [])
    return f"""Repo: {repo}. Run one cycle ({day}) of the marketing agent and report on it.

Setup (in the repo):
  uv venv && . .venv/bin/activate && uv pip install -e ".[dev]"
  ffmpeg must be on PATH (apt-get install -y ffmpeg if missing).
  export OPENAI_API_KEY="$ANSWERSNAP_OPENAI_KEY"   # the personal OpenAI key has no credits
  FAL_KEY is in your environment; renders cost about $0.22/s at 480p, $0.47/s at 720p, $0.80/s at
  1080p. Keep to --renders {renders} at {resolution}.
  The scraper drives the Chrome already running in your VM at http://localhost:29229.
  Own-post discovery requires a TikTok session in that Chrome. `mkt own login` reuses a verified
  login or submits TIKTOK_POST_HANDLE and TIKTOK_POST_PASSWORD from protected environment secrets.
  Do not print them, put them in prompts, export cookies, or copy them to shared services.
  If TikTok requires verification/CAPTCHA or the browser is signed into another account, stop
  that stage and report it. A fresh VM is not guaranteed to inherit a personal browser login.

State lives on the `{state_branch}` branch (sqlite db, daily reports, and site/ with the static dashboard and its clips),
checked out as a worktree:
  git fetch origin {state_branch} && git worktree add ../mkt-state {state_branch}
  (if the branch does not exist: git worktree add --detach ../mkt-state && cd ../mkt-state \\
   && git checkout --orphan {state_branch} && git rm -rfq . ; cd -)
  export MKT_DB=$PWD/../mkt-state/mkt.sqlite

Before running, take the API's db if it has one (it is the source of truth between runs; the human
dashboard reads its data there): mkt sync pull   (MKT_API_TOKEN is in your env)

Run:
  mkt daily {niche} {tag_str} --product "{product}" --renders {renders} --resolution {resolution}{ref_str} \\
    --report ../mkt-state/reports/{day}.md --dashboard ../mkt-state/site/index.html

Then:
1. Read the report. Every stage has ok/failed. If a stage failed because of a code bug, make the
   smallest fix, rerun that stage (the individual mkt commands are in the README), and open one PR
   against main per fix with the failure and the fix in the description. If it failed for a missing
   key, credit or network reason, do not work around it; say so in your summary.
2. Write down what you noticed, in plain words, for the Learnings page (the cycle's measured
   entry is already written by `mkt daily`; this is your reading of it): what the source videos
   actually do that the scripts should copy, what came out wrong and why, what you changed.
   2 to 8 sentences, no filler:  mkt learn add "<short title>" --body "<markdown>"
3. Push the finished db to the API: mkt sync push
4. Commit the state: cd ../mkt-state && git add -A && git commit -m "state: {day}" \\
   && git push origin HEAD:{state_branch}
5. Reply with a short summary: concept picked and why, how many scripts kept, renders made and their
   cost, how our posts did and how they compare with the market, top hooks/concepts on the scoreboard, what you fixed,
   PR links. Attach the rendered mp4s from data/renders/ and the report.

Rules: never post to TikTok, never message anyone, no bot accounts, no account warming,
no purchases, no account or password changes. Do not commit secrets. Do not merge PRs."""


class DailyReport:
    """Collects stage outcomes during `mkt daily` and renders the markdown report."""

    def __init__(self, niche: str, product: str):
        self.niche = niche
        self.product = product
        self.started = time.time()
        self.stages: list[dict] = []
        self.notes: list[str] = []

    def ok(self, name: str, seconds: float, note: str = "") -> None:
        self.stages.append({"stage": name, "status": "ok", "seconds": round(seconds), "note": note})

    def fail(self, name: str, err: BaseException) -> None:
        self.stages.append(
            {
                "stage": name,
                "status": "failed",
                "seconds": 0,
                "note": f"{type(err).__name__}: {err}",
            }
        )

    def skip(self, name: str, why: str) -> None:
        self.stages.append({"stage": name, "status": "skipped", "seconds": 0, "note": why})

    @property
    def failed(self) -> list[str]:
        return [s["stage"] for s in self.stages if s["status"] == "failed"]

    def write(self, path: Path, store: Store) -> Path:
        from .policy import concept_scores, winning_traits
        from .scoreboard import build

        run_start = int(self.started)
        lines = [
            f"# Daily run {datetime.fromtimestamp(self.started, UTC):%Y-%m-%d} - {self.niche}",
            "",
            f"Product: {self.product}",
            f"Finished in {round(time.time() - self.started)}s. "
            + ("All stages ok." if not self.failed else f"Failed: {', '.join(self.failed)}."),
            "",
            "## Stages",
            "",
            "| stage | status | s | note |",
            "|---|---|---|---|",
        ]
        lines += [
            f"| {s['stage']} | {s['status']} | {s['seconds']} | {s['note']} |" for s in self.stages
        ]

        scripts = store.rows(
            """SELECT s.id, s.hook, s.demo_score, c.name concept FROM scripts s
               LEFT JOIN concepts c ON c.id=s.concept_id
               WHERE s.created_at>=? AND s.product=? ORDER BY s.demo_score DESC, s.id""",
            (run_start, self.product),
        )
        lines += ["", "## Today's scripts", ""]
        if scripts:
            lines.append(f"Concept: {scripts[0]['concept']}. {len(scripts)} kept.")
            lines += [f"- s{s['id']} (demo {s['demo_score']}): {s['hook']}" for s in scripts[:8]]
        else:
            lines.append("none")

        renders = store.rows(
            """SELECT r.script_id, r.final_path, r.cost_usd, r.model FROM renders r
               JOIN scripts s ON s.id=r.script_id WHERE r.created_at>=? AND s.product=?""",
            (run_start, self.product),
        )
        lines += ["", "## Renders", ""]
        lines += [
            f"- s{r['script_id']}: {r['final_path']} ({r['model']}, ${r['cost_usd'] or 0:.2f})"
            for r in renders
        ] or ["none"]

        from .own import own_posts

        posts = own_posts(store)
        ours = build(store, group="ours")
        lines += ["", "## Our posts", ""]
        if posts:
            lines += [
                "| post | account | age h | views | concept | lift |",
                "|---|---|---|---|---|---|",
            ]
            for p in posts[:15]:
                lift = p["lift_72h"] if p["lift_72h"] is not None else p["lift_now"]
                lines.append(
                    f"| {p['url']} | {p['author']} | {p['age_h']} | {p['views_now'] or ''} | "
                    f"{p['concept'] or 'unmatched'} | {'' if lift is None else f'{lift:+.2f}'} |"
                )
        else:
            lines.append("No posts from our accounts yet.")
        if ours["hooks"]:
            lines += ["", "| hook_type | n | mean reward | win rate |", "|---|---|---|---|"]
            lines += [
                f"| {r['hook_type']} | {r['n']} | {r['mean_reward']:+.2f} | {r['win_rate']:.0%} |"
                for r in ours["hooks"][:6]
            ]
        if ours["stuck_accounts"]:
            lines += [
                "",
                "Possibly throttled: " + ", ".join(f["author"] for f in ours["stuck_accounts"]),
            ]

        sb = build(store, group="reference")
        lines += [
            "",
            "## Reference videos (research)",
            "",
            f"{len(sb['videos'])} videos, {sb['n_scored']} scored, {sb['n_tagged']} tagged.",
        ]
        for name, key in (("hooks", "hook_type"), ("concepts", "concept")):
            if sb[name]:
                lines += ["", f"| {key} | n | mean reward | win rate |", "|---|---|---|---|"]
                lines += [
                    f"| {r[key]} | {r['n']} | {r['mean_reward']:+.2f} | {r['win_rate']:.0%} |"
                    for r in sb[name][:6]
                ]

        from .compare import compare

        cmp = compare(store)
        lines += ["", "## Ours vs market", ""]
        if cmp:
            lines += [
                "| trait | value | market | n | ours | n | read |",
                "|---|---|---|---|---|---|---|",
            ]
            for r in cmp[:15]:
                m = "" if r["market"] is None else f"{r['market']:+.2f}"
                o = "" if r["ours"] is None else f"{r['ours']:+.2f}"
                lines.append(
                    f"| {r['trait']} | {str(r['value'])[:60]} | {m} | {r['market_n']} | {o} | "
                    f"{r['ours_n']} | {r['verdict']} |"
                )
        else:
            lines.append("Nothing scored on either side yet.")

        lines += ["", "## Policy", ""]
        traits = winning_traits(store)
        lines.append(traits or "Nothing scored yet; picks follow the radar's early score.")
        cs = concept_scores(store, self.niche)
        if cs:
            lines += ["", "| id | concept | prior | observed | n |", "|---|---|---|---|---|"]
            for c in cs[:10]:
                obs = "" if c["mean_reward"] is None else f"{c['mean_reward']:+.2f}"
                lines.append(
                    f"| {c['id']} | {c['name'][:40]} | {c['prior']:.2f} | {obs} | {c['n']} |"
                )
        if self.notes:
            lines += ["", "## Notes", ""] + [f"- {n}" for n in self.notes]

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n")
        return path
