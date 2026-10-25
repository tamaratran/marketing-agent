"""Two-hourly cron on Modal that asks the API to re-poll the cohort: POST /repoll records fresh
public stats for every cohort video younger than 8 days and rebuilds the feature rows. The work
happens on the API's own db, so there is no race with the daily session's sync.

Deploy once:   modal deploy deploy/modal_repoll.py
Try it:        modal run deploy/modal_repoll.py
Secrets:       the `mkt-devin` Modal secret needs MKT_API_TOKEN (and optionally MKT_API_URL).
"""

import os

import modal

app = modal.App("mkt-repoll")
image = modal.Image.debian_slim(python_version="3.12").pip_install("httpx>=0.27")

SCHEDULE = modal.Cron("23 */2 * * *")


@app.function(
    image=image, schedule=SCHEDULE, secrets=[modal.Secret.from_name("mkt-devin")], timeout=1500
)
def repoll() -> dict:
    import httpx

    url = os.environ.get("MKT_API_URL", "https://mkt-api.fly.dev").rstrip("/")
    r = httpx.post(
        f"{url}/repoll",
        headers={"Authorization": f"Bearer {os.environ['MKT_API_TOKEN']}"},
        timeout=1400,
    )
    r.raise_for_status()
    print(r.json())
    return r.json()


@app.local_entrypoint()
def main():
    print(repoll.remote())
