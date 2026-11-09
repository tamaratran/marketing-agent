# The harness preset

The marketing agent is not its own application. It is a generic agent harness
([tamaratran/agent](https://github.com/tamaratran/agent): a model loop, a toolbox of
files, shell and browser tools, and a web chat) wearing a four-file costume. These are
copies of those four files, kept here so the whole product can be read from one repo;
the live copies are in the agent repo under `products/marketing/`.

| File | What it does |
|---|---|
| `product.json` | Names the product, the repo to clone (this one), the setup command (`pip install -e . && mkt sync pull`), which keys to pass through from the server environment, the opening message, the briefing command (`mkt status --json`) and the two tabs (Learnings, Clips). |
| `prompt.md` | The extra system prompt: the job, the loop (research, scripts, clips, posting, measurement), the costs to state before spending, and the rules that do not bend (never post unless told, never message anyone, never sign in to GitHub). |
| `Dockerfile` | One image with Python, ffmpeg, headless Chromium, the harness and `mkt` installed from this repo at build time, plus `campaign.toml`. |
| `fly.toml` | One always-on Fly machine with a volume for sessions. |

How it works: the harness clones this repo, installs `mkt`, and runs `mkt status --json`
to brief the owner. From then on one standing conversation decides which `mkt` command to
run next, reads the result and explains it. The deterministic work (scraping, scoring,
grading, rendering, measuring) stays in `mkt`; the judgment is the conversation. No
credentials live in these files: the keys named in `product.json` are set as Fly secrets.
