# marketing-agent

An agent that learns which TikTok formats earn organic views and turns them into product videos.
Three modules in one repo, one SQLite store, one CLI (`mkt`):

| module | what it does | status |
|---|---|---|
| `research/` | Concept radar. Scrapes public TikTok hashtag pages in a real Chrome (no login, no API key), stores every video and its stats over time, ranks by an early-traction score, clusters videos into reusable concepts with an LLM. Polls any public video URL for views/likes/shares (scoreboard input). | working |
| `classifier/` | Watches a video (frames every 3s + transcript + caption + sound) and returns strict JSON tags: hook type and text, visual style, pacing, concept, product-by-5s, demo score. gpt-5.4 by default (gpt-5.4-mini flips labels between runs). | working |
| `video/` | Remixes a concept to a product (10-20 scripts, 1-3s hook, product on screen by 5s, scored for demoability), generates clips with Seedance 2.5 on fal.ai (Seedance 2.0 fast on Replicate as the cheap fallback), and cuts a captioned 1080x1920 H.264 with ffmpeg. `--provider stub` renders colour cards so the pipeline runs with no key. | working, needs `FAL_KEY` for real clips |

Not in scope by design: automated account warming, bot-run posting accounts, posting via API. Real
humans post from real accounts; the agent runs everything around them.

## Two kinds of video

Every video in the store is in exactly one of two groups, and they are never pooled:

- **Reference**: other people's videos scraped from niche hashtags for research. They feed the
  radar, concept clustering, the cohort panel and the controlled findings: what the market
  rewards right now.
- **Ours**: posts from our registered accounts (`mkt own add`, including their older posts, which
  set the baseline). They feed the picker's observed reward, the "our posts" section of the
  script prompt and the throttled-account check. `mkt own research` downloads and classifies them so we know which hook and style each
  one actually used.

`mkt scoreboard` prints both, `--group reference|ours` prints one. The daily report has a section
for each.

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
mkt poll <url> ...                    # record stats for posted videos
mkt scoreboard                        # reward per video, hooks/concepts ranked, throttled accounts
mkt compare                           # our posts vs the market: each hook/style/concept side by side
mkt dashboard tanning                 # static HTML (data/site/index.html) with clips copied next to it
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

### One-account login and feedback

```bash
# Supply TIKTOK_POST_HANDLE and TIKTOK_POST_PASSWORD through protected secrets, not CLI arguments.
mkt own login
mkt own add @youraccount --product "your product"
mkt own sync                      # niche and hashtags from campaign.toml
mkt own list
```

`own login` first verifies the signed-in identity and ownership controls on the profile. It
reuses that session without submitting a password. If logged out, it tries the saved credentials
once. Verification, CAPTCHA, login errors and a different signed-in account require human
attention in Chrome. It never logs anyone out, reads email, exports cookies or publishes anything.
The existing Chrome profile retains the login on this machine; a fresh scheduled VM may need
verification again. Do not put personal passwords or session cookies into shared Modal secrets.

`own sync` reads the account's recent profile feed (bounded scrolling, not a complete historical
export), verifies each returned author, and deduplicates post IDs. A missing feed is an error, not
zero posts. Posts older than registration provide a historical baseline only; they cannot be
matched to new scripts or added to the campaign cohort. Later posts are matched only to scripts
that existed when they were posted, in the same niche/product. Unmatched posts earn no concept
reward. Caption similarity is heuristic, not proof of attribution.

`mkt daily` syncs own posts before selecting the next concept. No new post means no new reward.
Historical lifetime-view baselines are not age-matched 72-hour controls; early lift is provisional.
Hashtag discovery remains an explicit fallback:
`mkt own add @youraccount --tag yourtag`, then `mkt own sync --source hashtag`.
Without profile access, that fallback can miss posts without those hashtags.

- Watch time and completion are not public for other people's videos. The scoreboard uses views,
  shares and saves normalised by age and follower count. For your own posts, TikTok Studio has them.
- TikTok's posting API cannot attach a library sound, so the editor bakes audio in (`--sound file.mp3`).
- Seedance 2.5 on fal takes 1-2 min per clip and costs about $0.22 per second at 480p, $0.47 at 720p; Replicate Seedance 2.0 fast is about $0.08 per second.
- Anonymous TikTok keyword search returns nothing; hashtag pages are the entry point.

## Letting Devin run it

`mkt daily` runs every stage in order and writes a markdown report; a stage that fails is recorded
and the rest still runs:

```bash
MKT_DB=../mkt-state/mkt.sqlite mkt daily --report ../mkt-state/reports/today.md   # everything from campaign.toml
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
session checks out as a worktree (`MKT_DB` points the CLI at it). Humans still do the posting.

Nothing runs on a schedule. The site's Runs page has one "Run cycle" button: it calls `POST /runs`
on the API with an empty body, and the API starts the Devin session with the campaign below.
`mkt daily` and `mkt devin kickoff` take the same defaults, so `mkt daily` alone runs a full cycle.
The 2-hourly cohort re-poll (`deploy/modal_repoll.py`) is the only scheduled job; it measures, it
does not create or post anything.

## campaign.toml

One file says what the loop is for; the API (`GET /campaign`, shown on Runs), the CLI (`mkt
campaign` prints it) and the Devin session all read it:

- `[account]` the TikTok handle a person posts from. Registered in the db at the start of every
  cycle; its results are the only ones that count as ours.
- `[niche]` name and hashtags whose fresh videos are measured and clustered into concepts.
- `[product]` name, site, App Store link, the description scripts are written to, the hashtags of
  the product's own TikToks (their format gets cloned) and reference images for the renders.
- `[cycle]` clips per cycle, resolution, ACU cap for the Devin session.

To market a different app, edit the file and merge; the API is redeployed from it. `MKT_*`
environment variables (`MKT_ACCOUNT`, `MKT_NICHE`, `MKT_TAGS`, `MKT_PRODUCT`, `MKT_PRODUCT_TAGS`,
`MKT_REFS`, `MKT_RENDERS`, `MKT_RESOLUTION`, `MKT_MAX_ACU`) override single fields for tests and
one-off runs and are otherwise unset. `MKT_CAMPAIGN` points at another file.

## Format cloning

`mkt daily ... --product-tag immersiveworkout --product-tag subwaysurfers` (API: `MKT_PRODUCT_TAGS`)
makes the run watch the product's own best-performing TikToks in the db (any age, ranked by views
discounted for account size, frames + transcript) and store their beat sheet as a `format` concept:
hook shot and delivery, shot order with timings, pacing, on-screen text budget, shared sound. The
picker takes it ahead of the fresh niche concepts until our own posts say otherwise, and the scripts
written from it follow it beat for beat and carry the sound the poster should pick in TikTok.
Without `--product-tag` (or before the db has product videos) the niche concepts are used as before.
