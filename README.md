# marketing-agent

An agent that learns which TikTok formats earn organic views and turns them into product videos.
Three modules in one repo, one SQLite store, one CLI (`mkt`):

| module | what it does | status |
|---|---|---|
| `research/` | Concept radar. Scrapes public TikTok hashtag pages in a real Chrome (no login, no API key), stores every video and its stats over time, ranks by an early-traction score, clusters videos into reusable concepts with an LLM. Polls any public video URL for views/likes/shares (scoreboard input). | working |
| `classifier/` | Watches a video (frames every 3s + transcript + caption + sound) and returns strict JSON tags: hook type and text, visual style, pacing, concept, product-by-5s, demo score. gpt-5.4 by default (gpt-5.4-mini flips labels between runs). | working |
| `creators/` | Creator ops. Drafts paid briefs from kept scripts (rate per 1k views, cap, deadline), keeps a roster of human creators, links their posts to briefs and scripts, computes payouts on settled 7-day views, and reports who posts and who stopped. Drafts only: nothing is sent to anyone. | working |
| `video/` | Remixes a concept to a product (10-20 scripts, 1-3s hook, product on screen by 5s, scored for demoability), generates clips with Seedance 2.5 on fal.ai (Seedance 2.0 fast on Replicate as the cheap fallback), and cuts a captioned 1080x1920 H.264 with ffmpeg. `--provider stub` renders colour cards so the pipeline runs with no key. | working, needs `FAL_KEY` for real clips |

Not in scope by design: automated account warming, bot-run posting accounts, posting via API. Real
humans post from real accounts; the agent runs everything around them.

## Setup

```bash
uv venv && . .venv/bin/activate
uv pip install -e ".[dev]"
cp .env.example .env   # fill in OPENAI_API_KEY, FAL_KEY
```

The scraper drives an existing Chrome over CDP (`CDP_URL`, default `http://localhost:29229`). Start
Chrome with `--remote-debugging-port=29229` or point it at any CDP endpoint. `ffmpeg` must be on PATH.

## Daily loop

```bash
mkt run tanning tanning selftanner --product "Glow, an app that previews your tan before you book"
```

which is the same as:

```bash
mkt scrape tanning selftanner         # ~30 videos per hashtag per scroll, newest first
mkt radar --max-age-h 72              # rank by early score (views/h, discounted by follower count)
mkt download --top 8                  # fetch the top videos through the browser
mkt classify                          # tag them (hook, style, concept, demo score)
mkt concepts tanning                  # cluster into 3-8 reusable formats, flag early ones
mkt scripts <concept_id> "Glow, ..."  # 12 scripts, keep demo_score >= 3
mkt render <script_id> --duration 10  # Seedance clip + captions -> data/renders/s<id>.mp4
mkt creators brief "Glow, ..." --concept 1 --rate 1 --cap 200   # paste into Discord/Sideshift
mkt creators add @amy --channel discord --rate 1
mkt creators post @amy https://www.tiktok.com/@amy/video/123 --brief 1 --script 4
mkt poll <url> ...                    # record stats for posted videos
mkt creators payouts                  # views/1k x rate, capped, settled after 7 days
mkt creators report                   # who posts, who stalled
mkt scoreboard                        # reward per video, hooks/concepts ranked, throttled accounts
```

## Scoreboard

`mkt scoreboard` turns raw views into a reward: `log10(views+1)`, winsorized at the 95th percentile,
minus the account's own median (or the niche median for accounts with under 3 videos). +1 means 10x
what that account normally gets. Hook types, concepts and visual styles are ranked by mean reward
with n, standard error and win rate, so a hook that won once on a huge account does not outrank one
that wins consistently. Videos under 24 h old are listed but not scored. Accounts whose last 3+
posts all sit under 1k views are flagged as possibly throttled.

## Feedback loop

`mkt run ... --product X` no longer scripts the concept with the highest early score. `policy.pick_concept`
samples a score per concept from the radar prior plus the scoreboard's observed mean reward (noise
shrinks with n), so with no data it follows the radar, with data it follows what earned views, and
it still explores. `mkt scripts` passes the scoreboard's winning and losing hooks, concepts and
styles into the prompt. `mkt policy <niche>` shows what the loop has learned.

## Known limits

- Watch time and completion are not public for other people's videos. The scoreboard uses views,
  shares and saves normalised by age and follower count. For your own posts, TikTok Studio has them.
- TikTok's posting API cannot attach a library sound, so the editor bakes audio in (`--sound file.mp3`).
- Seedance 2.5 on fal takes 1-2 min per clip and costs about $0.22 per second at 480p, $0.47 at 720p; Replicate Seedance 2.0 fast is about $0.08 per second.
- Anonymous TikTok keyword search returns nothing; hashtag pages are the entry point.

## Letting Devin run it

`mkt daily` runs every stage in order and writes a markdown report; a stage that fails is recorded
and the rest still runs:

```bash
MKT_DB=../mkt-state/mkt.sqlite mkt daily wearables smartring whoop ouraring \
  --product "a smart ring that tracks sleep, stress and recovery" --renders 1 --report ../mkt-state/reports/today.md
```

`mkt devin kickoff` starts a Devin session through the Devin API that does the judgment part: runs
`mkt daily`, reads the report, fixes a stage that broke (one PR per fix), pushes the db and report to
the `state` branch, and replies with the day's summary and the rendered clips.

```bash
export DEVIN_API_KEY=...   # Settings > Devin API > PATs
export DEVIN_ORG_ID=org-... # top of Settings > Devin API
mkt devin kickoff wearables smartring whoop ouraring --product "..." --dry-run   # show the prompt
mkt devin kickoff wearables smartring whoop ouraring --product "..."             # start it
mkt devin status <session_id>
```

State is kept out of `main`: the sqlite db and `reports/` live on the `state` branch, which each
session checks out as a worktree (`MKT_DB` points the CLI at it). Schedule the kickoff with cron or a
Devin Automation and the loop runs itself; humans still do the posting.
