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
    mode: str = "full",
    api_url: str = "",
) -> str:
    """What the Devin session is told. Self-contained: the session starts with no history.
    mode: "full" (measure, research, scripts, render), "research" (the same with --renders 0, so
    no fal spend; the site's Research again button) or "render" (only render the best of the
    latest script batch with `mkt render-latest`; the site's Generate clips button)."""
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    tag_str = " ".join(tags)
    ref_str = "".join(f' --ref "{r}"' for r in refs or [])
    if mode == "research":
        renders = 0
    if mode == "render":
        return f"""Repo: {repo}. Render the best {renders} clips from the latest script batch ({day}) and report on it.

Setup (in the repo):
  uv venv && . .venv/bin/activate && uv pip install -e ".[dev]"
  ffmpeg must be on PATH (apt-get install -y ffmpeg if missing).
  export OPENAI_API_KEY="$ANSWERSNAP_OPENAI_KEY"
  FAL_KEY is in your environment; renders cost about $0.22/s at 480p, $0.47/s at 720p, $0.80/s at
  1080p. Keep to --renders {renders} at {resolution}.

State lives on the `{state_branch}` branch, checked out as a worktree:
  git fetch origin {state_branch} && git worktree add ../mkt-state {state_branch}
  export MKT_DB=$PWD/../mkt-state/mkt.sqlite
  mkt sync pull   (MKT_API_TOKEN is in your env; the API's db is the source of truth)

Run:
  mkt render-latest --renders {renders} --resolution {resolution}{ref_str}
  mkt frames --out ../mkt-state/site/frames
  cp data/renders/*.mp4 ../mkt-state/site/renders/ 2>/dev/null || true

Then:
1. If a render failed for a missing key, credit ("User is locked", "Exhausted balance") or
   network reason, do not work around it; record it and say so:
   mkt stage render failed "<what happened, one line>"
   Otherwise: mkt stage render ok "<which scripts rendered>"
2. Watch each clip once. If one must not be posted (wrong game on the TV, a second person, the
   app icon as a shot), hold it with the reason:  mkt learn hold <script_id> "<reason>"
3. Push the db to the API: mkt sync push
4. Commit the state: cd ../mkt-state && git add -A && git commit -m "state: renders {day}" \
   && git push origin HEAD:{state_branch}
5. Post every clip you rendered and did not hold. The account owner asked for this: each call
   starts a posting session that uploads the clip from our account and registers the link:
   curl -sS -X POST {api_url}/renders/<script_id>/post -H "Authorization: Bearer $MKT_API_TOKEN"
   One call per clip, never twice for the same clip, never for a held clip.
Never message anyone and never post from any account but ours.
"""
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
   against main per fix with the failure and the fix in the description. Then record the rerun's
   outcome on the run so the site shows it instead of the first attempt's error:
   mkt stage <stage> ok|failed "<what happened, one line>"
   If it failed for a missing key, credit or network reason, do not work around it; say so in
   your summary.
2. Write down what you noticed, in plain words, for the Learnings page (the cycle's measured
   entry is already written by `mkt daily`; this is your reading of it): what the source videos
   actually do that the scripts should copy, what came out wrong and why, what you changed.
   2 to 8 sentences, no filler:  mkt learn add "<short title>" --body "<markdown>"
   If a clip must not be posted (wrong game on the TV, a second person, the app icon as a shot),
   hold it with the reason:  mkt learn hold <script_id> "<reason>"
   If you learned something every future script or clip must obey, make it a rule in one plain
   sentence; it goes into every script and video prompt from then on:  mkt learn rule "<sentence>"
3. Push the finished db to the API: mkt sync push
4. Commit the state: cd ../mkt-state && git add -A && git commit -m "state: {day}" \\
   && git push origin HEAD:{state_branch}
5. Reply with a short summary: concept picked and why, how many scripts kept, renders made and their
   cost, how our posts did and how they compare with the market, top hooks/concepts on the scoreboard, what you fixed,
   PR links. Attach the rendered mp4s from data/renders/ and the report.

Rules: never post to TikTok, never message anyone, no bot accounts, no account warming,
no purchases, no account or password changes. Do not commit secrets. Do not merge PRs."""


def record_stage(store: Store, niche: str, name: str, status: str, note: str = "") -> int | None:
    """After a stage is rerun by hand (a fix mid-cycle), write its new outcome onto the newest
    recorded run for the niche so the Runs page stops showing the first attempt's error. Returns
    the run id, or None when no run has been recorded yet."""
    import json

    rows = store.rows(
        "SELECT id, stages FROM runs WHERE niche=? ORDER BY id DESC LIMIT 1",
        (niche,),
    )
    if not rows:
        return None
    stages = json.loads(rows[0]["stages"] or "[]")
    for s in stages:
        if s["stage"] == name:
            s["status"], s["note"] = status, note
            break
    else:
        stages.append({"stage": name, "status": status, "seconds": 0, "note": note})
    overall = "failed" if any(s["status"] == "failed" for s in stages) else "ok"
    with store.conn() as c:
        c.execute(
            "UPDATE runs SET stages=?, status=?, finished_at=? WHERE id=?",
            (json.dumps(stages), overall, int(time.time()), rows[0]["id"]),
        )
    return rows[0]["id"]


def post_prompt(
    script_id: int,
    clip_url: str,
    text_lines: list[str],
    caption: str,
    sound: str,
    sound_url: str,
    handle: str,
    api_url: str,
    repo: str = DEFAULT_REPO,
) -> str:
    """What the Devin session that posts one clip is told. A person pressed Post on the site for
    exactly this clip; the session uploads it from our account through TikTok's own web uploader,
    adds the text with TikTok's text tool (so TikTok reads it as text, not pixels), picks the
    sound, posts, and registers the post so measurement starts. Nothing else."""
    lines = "\n".join(f"  {i + 1}. {ln}" for i, ln in enumerate(text_lines)) or "  (none)"
    sound_line = (
        f"{sound} ({sound_url})"
        if sound and sound_url
        else sound or "none picked: leave the sound off"
    )
    return f"""Repo: {repo}. Post ONE clip to TikTok from our account @{handle} and register it. A person
on the site pressed Post for exactly this clip; do not post anything else.

The clip (script #{script_id}), a clean export with no text burned in: {clip_url}
Download it with curl. Do not re-encode it.

Text to add with TikTok's own text tool in the web uploader (the "Text" button), one text box per
line, white bold, lower third of the frame, visible for the whole clip:
{lines}

Description (caption field): {caption}
Sound to add with the uploader's "Sounds" button: {sound_line}
If that exact sound cannot be found, search its title; if still missing, post with the clip's own
audio and say so in your summary.

Setup (in the repo): uv venv && . .venv/bin/activate && uv pip install -e ".[dev]"
The uploader runs in the Chrome already open in your VM at http://localhost:29229 (Playwright over
CDP). It must be signed in as @{handle}: `mkt own login` reuses a verified login or submits
TIKTOK_POST_HANDLE and TIKTOK_POST_PASSWORD from protected environment secrets. Never print them,
put them in prompts, export cookies or copy them anywhere. If TikTok asks for a verification code
or a CAPTCHA you cannot solve, or the browser is signed into a different account, stop and report;
do not post from another account.

Uploader notes: https://www.tiktok.com/tiktokstudio/upload has one hidden input[type=file]; set the
file on it. Click Cancel on the "automatic content checks" dialog and let the tour finish (never
remove its DOM nodes, the page breaks). Leave every setting TikTok chooses as it is, including its
AI-generated content label: do not toggle it on or off. Check the preview shows the text, then Post.

Then:
1. Open https://www.tiktok.com/@{handle} and copy the new post's URL (it can take a minute).
2. Register it so views start counting toward the script:
   curl -sS -X POST {api_url}/ours/posts -H "Authorization: Bearer $MKT_API_TOKEN" \\
     -H "content-type: application/json" -d '{{"url": "<post url>", "caption": "<description>"}}'
3. Reply with: the post URL, the text lines as added, the sound used, and anything TikTok changed
   or refused. Attach a screenshot of the posted video page.

Rules: one post, this clip only. Never message anyone, no bot accounts, no purchases, no account,
password or security changes. Do not edit the repo, open PRs or merge. Do not commit secrets."""


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

    def record(self, store: Store) -> int:
        """Store the outcome on the runs row the site created for this cycle (the newest one
        still open), or a new row when the cycle was started from the CLI, so the Runs page can
        show each stage and whether the cycle finished or failed."""
        import json

        with store.conn() as c:
            cols = {r[1] for r in c.execute("PRAGMA table_info(runs)")}
            for col, typ in (("status", "TEXT"), ("stages", "TEXT"), ("finished_at", "INTEGER")):
                if col not in cols:
                    c.execute(f"ALTER TABLE runs ADD COLUMN {col} {typ}")
        status = "failed" if self.failed else "ok"
        stages = json.dumps(self.stages)
        now = int(time.time())
        open_runs = store.rows(
            "SELECT id FROM runs WHERE finished_at IS NULL AND niche=? ORDER BY id DESC LIMIT 1",
            (self.niche,),
        )
        if open_runs:
            with store.conn() as c:
                c.execute(
                    "UPDATE runs SET status=?, stages=?, finished_at=? WHERE id=?",
                    (status, stages, now, open_runs[0]["id"]),
                )
            return open_runs[0]["id"]
        return store.insert(
            "runs",
            {
                "created_at": int(self.started),
                "session_id": "",
                "url": "",
                "niche": self.niche,
                "product": self.product,
                "note": "started from the CLI",
                "status": status,
                "stages": stages,
                "finished_at": now,
            },
        )

    def write(self, path: Path, store: Store) -> Path:
        from .policy import concept_scores, winning_traits
        from .scoreboard import build

        self.record(store)

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
            names = list(dict.fromkeys(s["concept"] or "?" for s in scripts))
            lines.append(
                f"{len(scripts)} script{'s' if len(scripts) != 1 else ''} across {len(names)} "
                f"format{'s' if len(names) != 1 else ''}: {', '.join(names)}."
            )
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
