"""Daily cron on Modal that calls `mkt devin kickoff`: one Devin session a day runs the loop.

Deploy once:   modal deploy deploy/modal_cron.py
Dry run:       modal run deploy/modal_cron.py --dry-run
Secrets:       modal secret create mkt-devin DEVIN_API_KEY=... DEVIN_ORG_ID=org-...
Config lives in env on the Modal secret too (optional): MKT_NICHE, MKT_TAGS (space separated),
MKT_PRODUCT, MKT_RENDERS, MKT_REPO. The function is a single HTTP call, so it costs nothing to
speak of; the Devin session it starts is where the ACUs go.
"""

import os

import modal

app = modal.App("mkt-daily-kickoff")
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("httpx>=0.27", "click>=8.1", "pydantic>=2", "rich>=13")
    .add_local_python_source("marketing_agent")
)

# 07:17 Pacific in summer, 06:17 in winter; off the hour on purpose.
SCHEDULE = modal.Cron("17 14 * * *")


@app.function(image=image, schedule=SCHEDULE, secrets=[modal.Secret.from_name("mkt-devin")])
def kickoff(dry_run: bool = False) -> str:
    from marketing_agent.orchestrator import DEFAULT_REPO, DevinClient, daily_prompt

    niche = os.environ.get("MKT_NICHE", "wearables")
    tags = os.environ.get("MKT_TAGS", "smartring whoop ouraring").split()
    product = os.environ.get("MKT_PRODUCT", "a smart ring that tracks sleep, stress and recovery")
    renders = int(os.environ.get("MKT_RENDERS", "1"))
    repo = os.environ.get("MKT_REPO", DEFAULT_REPO)
    prompt = daily_prompt(niche, tags, product, renders=renders, repo=repo)
    if dry_run:
        print(prompt)
        return "dry run"
    import time

    s = DevinClient().create_session(
        prompt,
        title=f"mkt daily {niche} {time.strftime('%Y-%m-%d')}",
        tags=["marketing-agent", niche, "cron"],
        repos=[repo],
        max_acu_limit=int(os.environ.get("MKT_MAX_ACU", "10")),
    )
    print(f"started {s['session_id']}: {s['url']}")
    return s["url"]


@app.local_entrypoint()
def main(dry_run: bool = False):
    print(kickoff.remote(dry_run=dry_run))
