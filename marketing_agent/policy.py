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
SHRINK_K = 2.0  # a concept's own posts outweigh its trait-based guess once it has about 2 of them
TRAIT_K = 2.0  # shrinkage on each trait value learned from our posts
MARKET_TRAIT_K = 10.0  # the market needs many videos per trait value before it says much
MARKET_TRAIT_WEIGHT = 0.25  # and what it says counts a quarter of what our own posts say
TRAITS = ("hook_type", "visual_style", "product_on_screen_by_5s", "pacing_bucket")


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


def our_clip_hooks(store: Store, top: int = 6) -> str:
    """Hooks of the clips we have already rendered, newest first, each with how often we used it.
    Not a reward: these are unposted or unmeasured, so the writer carries forward what we keep
    making rather than what the market or our posts have proven."""
    rows = store.rows(
        "SELECT s.hook, s.payload FROM renders r JOIN scripts s ON s.id=r.script_id "
        "ORDER BY r.created_at DESC LIMIT 40"
    )
    seen: dict[str, dict] = {}
    for r in rows:
        hook = (r["hook"] or "").strip()
        if not hook:
            continue
        try:
            body = json.loads(r["payload"] or "{}").get("body", "")
        except ValueError:
            body = ""
        entry = seen.setdefault(hook.lower(), {"hook": hook, "n": 0, "open": body.split(". ")[0]})
        entry["n"] += 1
    if not seen:
        return ""
    lines = [
        f'- "{e["hook"]}" (used {e["n"]}x): {e["open"][:140]}'
        if e["open"]
        else f'- "{e["hook"]}" (used {e["n"]}x)'
        for e in list(seen.values())[:top]
    ]
    return "our clips so far (rendered, not yet measured):\n" + "\n".join(lines)


def winning_traits(store: Store, tag: str | None = None, top: int = 3) -> str:
    """Short text for the script prompt: our own posts first, then the reference videos, then
    where the two disagree, each labelled so the writer knows which is which. In between, the hooks
    of our own rendered clips so the writer builds on them before any post is measured. Empty when
    nothing is scored or rendered."""
    from .compare import compare_text

    parts = (
        our_traits(store, top),
        our_clip_hooks(store),
        reference_traits(store, tag, top),
        compare_text(store, tag),
    )
    return "\n\n".join(t for t in parts if t)


def _tag_traits(tags: dict) -> dict:
    """The TRAITS of one classified video, from its tags payload."""
    from .cohort import bucket

    t = tags.get("tags", tags)
    return {
        "hook_type": t.get("hook_type"),
        "visual_style": t.get("visual_style"),
        "product_on_screen_by_5s": t.get("product_on_screen_by_5s"),
        "pacing_bucket": bucket(
            t.get("pacing_cuts_per_10s"), [2, 4, 7], ["slow", "medium", "fast", "frantic"]
        ),
    }


def concept_traits(store: Store, video_ids: list[str]) -> dict:
    """What a concept looks like: the most common value of each trait over its classified
    member videos. A trait is None when no member has been classified."""
    tags = store.tags_for(video_ids)
    votes: dict[str, dict] = {k: {} for k in TRAITS}
    for t in tags.values():
        for k, v in _tag_traits(t).items():
            if v is not None:
                votes[k][v] = votes[k].get(v, 0) + 1
    return {k: (max(v, key=v.get) if v else None) for k, v in votes.items()}


def _effects(samples: list[tuple[dict, float]], k: float) -> dict[str, dict]:
    """trait -> value -> {effect, n}: mean reward per trait value, shrunk toward 0 by k pseudo
    observations, so one lucky post cannot define a trait."""
    acc: dict[str, dict[object, list[float]]] = {t: {} for t in TRAITS}
    for traits, r in samples:
        for t in TRAITS:
            v = traits.get(t)
            if v is not None:
                acc[t].setdefault(v, []).append(r)
    return {
        t: {
            v: {"effect": round(sum(rs) / (len(rs) + k), 3), "n": len(rs)} for v, rs in vals.items()
        }
        for t, vals in acc.items()
    }


def trait_effects(store: Store, niche: str, concepts: list[dict]) -> dict:
    """What each trait value has earned, from our own posts (full weight) and from the niche's
    reference videos (MARKET_TRAIT_WEIGHT, more shrinkage). Our posts use their own classifier
    tags when they have them, else the traits of the concept they were scripted from."""
    from .own import own_post_rewards
    from .scoreboard import build

    by_id = {c["id"]: c for c in concepts}
    own = own_post_rewards(store)
    tags = store.tags_for([p["video_id"] for p in own])
    samples = []
    for p in own:
        if p["video_id"] in tags:
            samples.append((_tag_traits(tags[p["video_id"]]), p["reward"]))
        elif p["concept_id"] in by_id:
            samples.append((by_id[p["concept_id"]]["traits"], p["reward"]))
    ours = _effects(samples, TRAIT_K)
    market_rows = build(store, tags=store.niche_tags(niche) or None, group="reference")["videos"]
    market = _effects(
        [(_tag_traits({"tags": v}), v["reward"]) for v in market_rows if v["reward"] is not None],
        MARKET_TRAIT_K,
    )
    return {"ours": ours, "market": market}


def _trait_bonus(traits: dict, effects: dict) -> tuple[float, float, list[dict]]:
    """(own bonus, market bonus, per-trait detail) for one concept's trait profile. Bonuses are
    the mean over its known traits, not the sum: one post teaches all four traits at once, so
    adding them up would count that post four times."""
    own, market, detail = [], [], []
    for t in TRAITS:
        v = traits.get(t)
        if v is None:
            continue
        o = effects["ours"].get(t, {}).get(v)
        m = effects["market"].get(t, {}).get(v)
        own_e = o["effect"] if o else 0.0
        market_e = (m["effect"] * MARKET_TRAIT_WEIGHT) if m else 0.0
        own.append(own_e)
        market.append(market_e)
        detail.append(
            {
                "trait": t,
                "value": v,
                "ours": round(own_e, 3),
                "ours_n": o["n"] if o else 0,
                "market": round(market_e, 3),
                "market_n": m["n"] if m else 0,
            }
        )
    mean = lambda xs: round(sum(xs) / len(xs), 3) if xs else 0.0  # noqa: E731
    return mean(own), mean(market), detail


def concept_scores(store: Store, niche: str, tag: str | None = None) -> list[dict]:
    """Each stored concept for the niche with a prior (log early score, scaled) and what has
    been learned about it: `learned` = (SHRINK_K * trait bonus + sum of its own posts' rewards)
    / (SHRINK_K + n). The trait bonus is what its hook type, visual style, product timing and
    pacing have earned across all our posts (and, at a quarter weight, across the niche), so a
    format we have never posted still inherits what similar formats taught us, and a format that
    comes back under a new name after the next research run keeps what it learned."""
    from .own import own_rewards

    ours = own_rewards(store)
    rows = store.rows(
        "SELECT id, name, description, early_score, video_ids, payload FROM concepts "
        "WHERE niche=? ORDER BY created_at DESC",
        (niche,),
    )

    # Each research run stores a fresh row per concept, so our posts can point at an older row of
    # the same name; pool them by name so their results reach the row the picker uses. The
    # product's own cloned format is one concept however the model titles its beat sheet, so
    # every format-kind row pools under one key and only the newest one is a candidate.
    def kind_of(c: dict) -> str:
        try:
            return json.loads(c.get("payload") or "{}").get("kind", "")
        except ValueError:
            return ""

    def key(c: dict) -> str:
        return "format" if kind_of(c) == "format" else c["name"]

    by_name: dict[str, list[dict]] = {}
    for c in rows:
        if c["id"] in ours:
            by_name.setdefault(key(c), []).append(ours[c["id"]])
    for c in rows:
        try:
            c["traits"] = concept_traits(store, json.loads(c.get("video_ids") or "[]"))
        except ValueError:
            c["traits"] = dict.fromkeys(TRAITS)
    effects = trait_effects(store, niche, rows)
    seen, out = set(), []
    for c in rows:
        k, kind = key(c), kind_of(c)
        if k in seen:
            continue
        seen.add(k)
        c.pop("payload", None)
        c.pop("video_ids", None)
        prior = math.log10((c["early_score"] or 0) + 1) / 3  # ~0..1 for 1..1000 early score
        hits = by_name.get(k, [])
        n = sum(h["n"] for h in hits)
        total = sum(h["mean_reward"] * h["n"] for h in hits)
        own_bonus, market_bonus, detail = _trait_bonus(c["traits"], effects)
        trait_bonus = own_bonus + market_bonus
        out.append(
            {
                **c,
                "kind": kind,
                "prior": round(prior, 3),
                "mean_reward": round(total / n, 3) if n else None,
                "n": n,
                "trait_bonus": round(trait_bonus, 3),
                "trait_detail": detail,
                "learned": round((SHRINK_K * trait_bonus + total) / (SHRINK_K + n), 3),
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
    """Sample a score per concept from N(prior + learned, sd shrinking with n) and take the max.
    With no posts this is a noisy argmax on early score plus what the format's traits have earned
    elsewhere; with posts it shifts to what actually earned views, still occasionally trying a
    loser."""
    rng = rng or random.Random()
    cands = concept_scores(store, niche)
    if not cands:
        return None
    for c in cands:
        mean = c["prior"] + c["learned"]
        sd = EXPLORE_SD / math.sqrt(1 + c["n"])
        c["sampled"] = round(rng.gauss(mean, sd), 3)
    return max(cands, key=lambda c: c["sampled"])
