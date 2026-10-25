"""Closes the loop: the scoreboard's rewards decide which concept gets scripted next and what the
script writer is told has worked. Thompson-style sampling over concepts (mean reward with a prior
from the radar's early score) keeps roughly a quarter of picks exploring instead of always taking
the current leader."""

import math
import random

from .scoreboard import build
from .store import Store

EXPLORE_SD = 0.35


def winning_traits(store: Store, tag: str | None = None, top: int = 3) -> str:
    """Short text for the script prompt: which hooks, concepts and styles have beaten baseline,
    with n, and which have lost. Empty when nothing has been scored yet."""
    sb = build(store, tag)
    parts = []
    for name, key in (("hooks", "hook_type"), ("concepts", "concept"), ("styles", "visual_style")):
        rows = sb[name]
        if not rows:
            continue
        win = [
            f"{r[key]} ({r['mean_reward']:+.2f}, n={r['n']})"
            for r in rows[:top]
            if r["mean_reward"] > 0
        ]
        lose = [
            f"{r[key]} ({r['mean_reward']:+.2f}, n={r['n']})"
            for r in rows[-top:]
            if r["mean_reward"] < 0
        ]
        if win:
            parts.append(f"{name} that beat the account baseline: " + "; ".join(win))
        if lose:
            parts.append(f"{name} that lost: " + "; ".join(lose))
    return "\n".join(parts)


def concept_scores(store: Store, niche: str, tag: str | None = None) -> list[dict]:
    """Each stored concept for the niche with a prior (log early score, scaled) and, when the
    classifier's concept label matches, the observed mean reward and n."""
    sb = build(store, tag)
    observed = {r["concept"].lower(): r for r in sb["concepts"]}
    rows = store.rows(
        "SELECT id, name, description, early_score FROM concepts WHERE niche=? ORDER BY created_at DESC",
        (niche,),
    )
    seen, out = set(), []
    for c in rows:
        if c["name"] in seen:
            continue
        seen.add(c["name"])
        prior = math.log10((c["early_score"] or 0) + 1) / 3  # ~0..1 for 1..1000 early score
        obs = observed.get(c["name"].lower())
        out.append(
            {
                **c,
                "prior": round(prior, 3),
                "mean_reward": obs["mean_reward"] if obs else None,
                "n": obs["n"] if obs else 0,
            }
        )
    return out


def pick_concept(store: Store, niche: str, rng: random.Random | None = None) -> dict | None:
    """Sample a score per concept from N(prior + observed mean, sd shrinking with n) and take the
    max. With no observations this is a noisy argmax on early score; with data it shifts to what
    actually earned views, while still occasionally trying a loser."""
    rng = rng or random.Random()
    cands = concept_scores(store, niche)
    if not cands:
        return None
    for c in cands:
        mean = c["prior"] + (c["mean_reward"] or 0.0)
        sd = EXPLORE_SD / math.sqrt(1 + c["n"])
        c["sampled"] = round(rng.gauss(mean, sd), 3)
    return max(cands, key=lambda c: c["sampled"])
