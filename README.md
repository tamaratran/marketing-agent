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
mkt scoreboard                        # views over time joined with tags
```

## Known limits

- Watch time and completion are not public for other people's videos. The scoreboard uses views,
  shares and saves normalised by age and follower count. For your own posts, TikTok Studio has them.
- TikTok's posting API cannot attach a library sound, so the editor bakes audio in (`--sound file.mp3`).
- Seedance 2.5 on fal takes 1-2 min per clip and costs about $0.22 per second at 480p, $0.47 at 720p; Replicate Seedance 2.0 fast is about $0.08 per second.
- Anonymous TikTok keyword search returns nothing; hashtag pages are the entry point.
