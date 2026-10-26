"""Closes the loop: the scoreboard's rewards decide which concept gets scripted next and what the
script writer is told has worked. Thompson-style sampling over concepts (mean reward with a prior
from the radar's early score) keeps exploring instead of always taking the current leader. The
product's own cloned format starts FORMAT_EDGE above the best market format, so it wins about 3 in
4 picks and the rest test market formats."""

import json
import math
import random

from .scoreboard import build
from .store import Store

EXPLORE_SD = 0.35
FORMAT_EDGE = 0.65  # clone wins ~75% of picks against 7 market formats with EXPLORE_SD noise


def controlled_traits(store: Store, outcome: str = "lift_72h") -> str:
    """Text from the latest controlled findings: trait levels called better or worse once account
    size, niche, length and posting hour are held fixed. Empty while the panel is still
    collecting (fewer than MIN_N videos per cell at 72h), so the raw tables are used instead."""
    from .analysis import TRAITS, latest_findings

    f = latest_findings(store)
    if not f or f["status"]["reached"].get("72h", 0) < f["min_n"]:
        return ""
    parts = []
    for trait in TRAITS:
        fit = f["fits"].get(outcome, {}).get("pooled", {}).get(trait, {})
        ref = fit.get("reference")
        calls = [
            f"{lvl['level']} {lvl['coef']:+.2f} vs {ref} (n={lvl['n']}"
            + (", travels across niches" if lvl.get("travels") else "")
            + ")"
            for lvl in fit.get("levels", [])
            if lvl["verdict"] in ("better", "worse")
        ]
        if calls:
            parts.append(f"{trait}: " + "; ".join(calls))
    if not parts:
        return ""
    return (
        "Reference videos in the niche (other accounts). "
        "Controlled for account size, niche, length and posting hour "
        f"({f['status']['videos']} cohort videos):\n" + "\n".join(parts)
    )


def our_traits(store: Store, top: int = 3) -> str:
    """What our own posts have shown so far: concepts and hooks by lift over our accounts'
    baselines. Empty until a post has a reward."""
    from .own import own_posts

    by_concept: dict[str, list[float]] = {}
    for p in own_posts(store):
        r = p["lift_72h"] if p["lift_72h"] is not None else p["lift_now"]
        if r is not None and p["concept"]:
            by_concept.setdefault(p["concept"], []).append(r)
    parts = []
    if by_concept:
        ranked = sorted(by_concept.items(), key=lambda kv: -sum(kv[1]) / len(kv[1]))
        parts.append(
            "concepts: "
            + "; ".join(f"{k} ({sum(v) / len(v):+.2f}, n={len(v)})" for k, v in ranked[:top])
        )
    hooks = build(store, group="ours")["hooks"]
    if hooks:
        parts.append(
            "hooks: "
            + "; ".join(
                f"{h['hook_type']} ({h['mean_reward']:+.2f}, n={h['n']})" for h in hooks[:top]
            )
        )
    if not parts:
        return ""
    return "Our own posts, lift over our accounts' usual views:\n" + "\n".join(parts)


def reference_traits(store: Store, tag: str | None = None, top: int = 3) -> str:
    """What reference videos in the niche show. Prefers the controlled findings; until those
    exist it falls back to the raw scoreboard tables, labelled as such."""
    controlled = controlled_traits(store)
    if controlled:
        return controlled
    sb = build(store, tag, group="reference")
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
    if parts:
        parts.insert(
            0,
            "Reference videos in the niche (other accounts), raw, not yet controlled for account "
            "size or niche, small n:",
        )
    return "\n".join(parts)


def winning_traits(store: Store, tag: str | None = None, top: int = 3) -> str:
    """Short text for the script prompt: our own posts first, then the reference videos, then
    where the two disagree, each labelled so the writer knows which is which. Empty when nothing
    is scored."""
    from .compare import compare_text

    parts = (our_traits(store, top), reference_traits(store, tag, top), compare_text(store, tag))
    return "\n\n".join(t for t in parts if t)


def concept_scores(store: Store, niche: str, tag: str | None = None) -> list[dict]:
    """Each stored concept for the niche with a prior (log early score, scaled) and the observed
    mean reward and n from our own posts of that concept (see own.own_rewards)."""
    from .own import own_rewards

    ours = own_rewards(store)
    rows = store.rows(
        "SELECT id, name, description, early_score, payload FROM concepts WHERE niche=? ORDER BY created_at DESC",
        (niche,),
    )
    seen, out = set(), []
    for c in rows:
        if c["name"] in seen:
            continue
        seen.add(c["name"])
        try:
            kind = json.loads(c.pop("payload") or "{}").get("kind", "")
        except ValueError:
            kind = ""
        prior = math.log10((c["early_score"] or 0) + 1) / 3  # ~0..1 for 1..1000 early score
        obs = ours.get(c["id"])
        out.append(
            {
                **c,
                "kind": kind,
                "prior": round(prior, 3),
                "mean_reward": obs["mean_reward"] if obs else None,
                "n": obs["n"] if obs else 0,
            }
        )
    # A beat sheet of the product's own proven videos is the safest bet, so it leads the best
    # market format by FORMAT_EDGE: favoured, but close enough that the noise still tests others.
    market = [c["prior"] for c in out if c["kind"] != "format"]
    for c in out:
        if c["kind"] == "format":
            c["prior"] = round(max(market, default=0.0) + FORMAT_EDGE, 3)
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
