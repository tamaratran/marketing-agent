"""Our own posts: the self-improving half of the loop.

We never post by machine, but we must notice what humans posted from our accounts and learn from
it. Discovery works without any login: every clip's caption carries the campaign hashtag, the
hashtag page is scrapable unsigned (profiles are not), so `sync_own` scans the campaign tag plus
the niche tags, keeps posts whose author is one of our accounts, matches each to the script it
came from by caption similarity, enrols it in the cohort flagged `ours=1`, and snapshots the
account. From then on the 2-hourly repoll gives it a curve like any other video.

`own_rewards` turns those posts into the bandit's reward: per concept, the mean lift of our posts
(log10 views minus the account's own baseline, at 72h when reached, else at the latest poll with
an age discount), so the picker learns from what we actually posted, not only from the market."""

from __future__ import annotations

import difflib
import json
import math
import time

from .cohort import snapshot_creator, views_at
from .store import Store

MIGRATIONS = [
    "ALTER TABLE videos ADD COLUMN ours INTEGER DEFAULT 0",
    "ALTER TABLE videos ADD COLUMN script_id INTEGER",
    """CREATE TABLE IF NOT EXISTS own_accounts (
         handle TEXT PRIMARY KEY, campaign_tag TEXT, product TEXT, added_at INTEGER)""",
]
MIN_MATCH = 0.45


def migrate(store: Store) -> None:
    with store.conn() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(videos)")}
        for sql in MIGRATIONS:
            if sql.startswith("ALTER") and sql.split("ADD COLUMN ")[1].split()[0] in cols:
                continue
            c.execute(sql)


def add_account(store: Store, handle: str, campaign_tag: str, product: str = "") -> None:
    migrate(store)
    with store.conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO own_accounts VALUES (?,?,?,?)",
            (
                handle.lstrip("@").lower(),
                campaign_tag.lstrip("#").lower(),
                product,
                int(time.time()),
            ),
        )


def accounts(store: Store) -> list[dict]:
    migrate(store)
    return store.rows("SELECT * FROM own_accounts ORDER BY added_at")


def match_script(store: Store, desc: str, days: int = 60) -> tuple[int | None, float]:
    """The script whose hook + captions read most like this caption, if close enough."""
    since = int(time.time()) - days * 86400
    best, best_r = None, 0.0
    for s in store.rows(
        "SELECT id, hook, payload FROM scripts WHERE created_at>=? ORDER BY created_at DESC",
        (since,),
    ):
        caps = " ".join(json.loads(s["payload"] or "{}").get("captions") or [])
        text = f"{s['hook']} {caps}".lower()
        r = difflib.SequenceMatcher(None, (desc or "").lower(), text).ratio()
        r = max(
            r,
            difflib.SequenceMatcher(None, (desc or "").lower(), (s["hook"] or "").lower()).ratio(),
        )
        if r > best_r:
            best, best_r = s["id"], r
    return (best, round(best_r, 3)) if best_r >= MIN_MATCH else (None, round(best_r, 3))


def sync_own(
    store: Store, cdp_url: str, niche: str, niche_tags: list[str], scrolls: int = 4
) -> dict:
    """Find new posts from our accounts via the campaign and niche hashtag pages, enrol them."""
    from .research.tiktok_browser import profile_stats, scrape_hashtag_sync

    migrate(store)
    ours = {a["handle"]: a for a in accounts(store)}
    if not ours:
        return {"accounts": 0, "found": 0, "new": 0}
    tags = sorted({a["campaign_tag"] for a in ours.values() if a["campaign_tag"]} | set(niche_tags))
    found = new = 0
    for tag in tags:
        for r in scrape_hashtag_sync(tag, cdp_url, scrolls=scrolls):
            if (r.get("author") or "").lower() not in ours:
                continue
            found += 1
            known = store.rows("SELECT ours FROM videos WHERE id=?", (r["id"],))
            store.upsert_video(r)
            if known and known[0]["ours"]:
                continue
            sid, score = match_script(store, r.get("desc", ""))
            with store.conn() as c:
                c.execute(
                    "UPDATE videos SET ours=1, script_id=?, niche=?, cohort_at=COALESCE(cohort_at, ?) WHERE id=?",
                    (sid, niche, int(time.time()), r["id"]),
                )
            new += 1
    for handle in ours:
        try:
            snapshot_creator(store, handle, stats=profile_stats(handle))
        except Exception:  # noqa: BLE001 - baseline is best effort
            snapshot_creator(store, handle)
    return {"accounts": len(ours), "found": found, "new": new}


def own_posts(store: Store) -> list[dict]:
    """Every post from our accounts with its script, concept, baseline and current lift."""
    migrate(store)
    rows = store.rows(
        """SELECT v.id, v.url, v.author, v.desc, v.create_time, v.duration, v.source_tag, v.niche,
                  v.script_id, s.hook, s.concept_id, c.name concept
           FROM videos v LEFT JOIN scripts s ON s.id=v.script_id
           LEFT JOIN concepts c ON c.id=s.concept_id WHERE v.ours=1 ORDER BY v.create_time DESC"""
    )
    now = int(time.time())
    for v in rows:
        obs = store.rows(
            "SELECT observed_at, views FROM observations WHERE video_id=? ORDER BY observed_at",
            (v["id"],),
        )
        curve = [((o["observed_at"] - v["create_time"]) / 3600, o["views"]) for o in obs]
        snap = store.rows(
            "SELECT median_log_views, n_posts FROM creator_snapshots WHERE author=? ORDER BY taken_at DESC LIMIT 1",
            (v["author"],),
        )
        base = (
            snap[0]["median_log_views"]
            if snap and snap[0]["median_log_views"] is not None
            else None
        )
        v["age_h"] = round((now - v["create_time"]) / 3600, 1)
        v["views_now"] = obs[-1]["views"] if obs else None
        v["views_72h"] = views_at(curve, 72)
        v["baseline_log"] = base
        v["lift_72h"] = (
            (math.log10(v["views_72h"]) - base) if v["views_72h"] and base is not None else None
        )
        latest = v["views_now"]
        v["lift_now"] = (math.log10(latest) - base) if latest and base is not None else None
        v["n_obs"] = len(obs)
    return rows


def own_rewards(store: Store) -> dict[int, dict]:
    """concept_id -> {mean_reward, n} from our posts. 72h lift when available, else the latest
    lift discounted by age (a 6h-old post counts a third of a 72h one) so early posts nudge the
    picker without dominating it."""
    agg: dict[int, list[float]] = {}
    for p in own_posts(store):
        if p["concept_id"] is None:
            continue
        if p["lift_72h"] is not None:
            r = p["lift_72h"]
        elif p["lift_now"] is not None:
            r = p["lift_now"] * min(1.0, (p["age_h"] / 72) ** 0.5)
        else:
            continue
        agg.setdefault(p["concept_id"], []).append(r)
    return {cid: {"mean_reward": round(sum(v) / len(v), 3), "n": len(v)} for cid, v in agg.items()}
