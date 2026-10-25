"""Concept radar: early-signal scoring and LLM clustering of fresh videos into reusable concepts."""

import json
import math
import time

from openai import OpenAI

from ..store import Store


def early_score(row: dict, now: int | None = None) -> float:
    """Views per hour, discounted by account size, boosted for freshness.
    High when a small account is pulling views fast on a recent post."""
    now = now or int(time.time())
    age_h = max((now - row["create_time"]) / 3600, 0.5)
    views = row.get("views") or 0
    followers = max(row.get("followers") or 1, 1)
    vph = views / age_h
    size_penalty = math.log10(followers + 10)
    freshness = 1.0 if age_h < 48 else 48 / age_h
    return round(vph / size_penalty * freshness, 1)


def rank(store: Store, tag: str | None = None, max_age_h: int = 72, limit: int = 40) -> list[dict]:
    now = int(time.time())
    rows = [r for r in store.latest(tag) if (now - r["create_time"]) / 3600 <= max_age_h]
    for r in rows:
        r["early_score"] = early_score(r, now)
        r["age_h"] = round((now - r["create_time"]) / 3600, 1)
    rows.sort(key=lambda r: -r["early_score"])
    return rows[:limit]


CLUSTER_PROMPT = """You are grouping fresh TikTok videos from one niche into reusable CONCEPTS
(formats someone else could film tomorrow with a different product). You get one line per video:
id | age_h | views | followers | duration | sound | caption | classifier concept (if any).

Return JSON: {"concepts": [{"name": short name, "description": one sentence describing the format,
"hook_pattern": how the first 2 seconds work, "video_ids": [...], "why_early": one sentence on whether
this looks early (few posts, fast views on small accounts) or saturated}]}.
Every video goes in exactly one concept. Make 3 to 8 concepts. Prefer formats over topics."""


def cluster(store: Store, niche: str, rows: list[dict], model: str = "gpt-5.4") -> list[dict]:
    tags = store.tags_for([r["id"] for r in rows])
    lines = []
    for r in rows:
        t = tags.get(r["id"], {})
        lines.append(
            f"{r['id']} | {r['age_h']}h | {r['views']} | {r['followers']} | {r['duration']}s | "
            f"{(r['music'] or '')[:30]} | {(r['desc'] or '')[:100]} | {t.get('concept', '')}"
        )
    client = OpenAI()
    resp = client.responses.create(
        model=model,
        input=[{"role": "user", "content": CLUSTER_PROMPT + "\n\n" + "\n".join(lines)}],
        text={"format": {"type": "json_object"}},
    )
    concepts = json.loads(resp.output_text)["concepts"]
    by_id = {r["id"]: r for r in rows}
    out = []
    for c in concepts:
        members = [by_id[i] for i in c.get("video_ids", []) if i in by_id]
        if not members:
            continue
        score = round(sum(m["early_score"] for m in members) / len(members), 1)
        cid = store.insert(
            "concepts",
            {
                "niche": niche,
                "created_at": int(time.time()),
                "name": c["name"],
                "description": c["description"],
                "video_ids": json.dumps([m["id"] for m in members]),
                "early_score": score,
                "payload": json.dumps(c),
            },
        )
        out.append(
            {
                **c,
                "id": cid,
                "early_score": score,
                "n": len(members),
                "top_views": max(m["views"] or 0 for m in members),
            }
        )
    out.sort(key=lambda c: -c["early_score"])
    return out
