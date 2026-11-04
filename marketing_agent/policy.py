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


def controlled_traits(store: Store, outcome: str | None = None) -> str:
    """Text from the latest controlled findings: trait levels called better or worse once account
    size, niche, length and posting hour are held fixed. Empty while the panel is still
    collecting (fewer than MIN_N scored videos), so the raw tables are used instead."""
    from .analysis import DEFAULT_OUTCOME, TRAITS, latest_findings

    outcome = outcome or DEFAULT_OUTCOME
    f = latest_findings(store)
    if not f or f["status"]["reached"].get("scored", 0) < f["min_n"]:
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


def verdicts(store: Store, niche: str, top: int = 4) -> str:
    """What our own posts have proven, with how much evidence sits behind each line, so the
    writer cannot mistake one post for a pattern. Formats first (measured, then never posted),
    then traits, then the hooks we already used, each marked measured or untested."""
    from .own import own_post_rewards

    cands = concept_scores(store, niche)
    if not cands:
        return ""
    measured = sorted((c for c in cands if c["n"]), key=lambda c: -c["mean_reward"])
    lines = []
    if measured:
        lines.append("Our formats, measured against niche videos of the same age and account size:")
        for c in measured:
            tag = "weak evidence, one post" if c["n"] == 1 else f"{c['n']} posts"
            lines.append(
                f"- {c['name']}: {c['mean_reward']:+.2f} ({tag}); the picker now scores it "
                f"{c['learned']:+.2f} after what its traits earned elsewhere"
            )
    untested = [c["name"] for c in cands if not c["n"]]
    if untested:
        lines.append("Never posted: " + ", ".join(untested[: top * 2]) + ".")
    traits: dict[tuple[str, object], dict] = {}
    for c in cands:
        for d in c.get("trait_detail", []):
            if d["ours_n"]:
                traits[(d["trait"], d["value"])] = d
    if traits:
        lines.append("Traits of our posts so far (score shrinks toward 0 with few posts):")
        for d in sorted(traits.values(), key=lambda d: -abs(d["ours"]))[:top]:
            lines.append(
                f"- {d['trait']}={d['value']}: {d['ours']:+.2f} over {d['ours_n']} post(s)"
            )
    posted = {p["video_id"]: p["reward"] for p in own_post_rewards(store)}
    hooks = _our_hooks(store, posted)
    if hooks:
        lines.append(
            "Hooks we have already rendered (measured where a post exists, otherwise untested, so frequency means nothing):"
        )
        lines += hooks[:top]
    if not lines:
        return ""
    if len(posted) < 3:
        lines.append(
            f"Only {len(posted)} post(s) measured so far: treat every line above as a lead to test, not a rule."
        )
    return "\n".join(lines)


def _our_hooks(store: Store, posted: dict[str, float]) -> list[str]:
    from .learnings import migrate

    migrate(store)  # renders.hold_reason exists on every db from here on
    rows = store.rows(
        "SELECT s.id, s.hook, v.id video_id FROM renders r JOIN scripts s ON s.id=r.script_id "
        "LEFT JOIN videos v ON v.script_id=s.id AND v.ours=1 "
        "WHERE r.hold_reason IS NULL ORDER BY r.created_at DESC LIMIT 40"
    )
    seen: dict[str, dict] = {}
    for r in rows:
        hook = (r["hook"] or "").strip()
        if not hook:
            continue
        e = seen.setdefault(hook.lower(), {"hook": hook, "n": 0, "rewards": []})
        e["n"] += 1
        if r["video_id"] in posted:
            e["rewards"].append(posted[r["video_id"]])
    out = []
    for e in seen.values():
        if e["rewards"]:
            m = sum(e["rewards"]) / len(e["rewards"])
            out.append(f'- "{e["hook"]}": measured {m:+.2f} over {len(e["rewards"])} post(s)')
        else:
            out.append(f'- "{e["hook"]}": untested (rendered {e["n"]}x)')
    return out


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
    """Short text for the script prompt: standing rules from review first, then what our own
    posts have proven (with the evidence behind each line), then the reference videos, then where
    the two disagree, each labelled so the writer knows which is which. Empty when nothing is
    scored, rendered or ruled."""
    from . import campaign as campaign_cfg
    from .compare import compare_text
    from .learnings import notes_text, rules_text
    from .rubric import LEARNING_TITLE, digest

    c = campaign_cfg.load()
    niche = c.niche.name
    parts = (
        rules_text(store, niche),
        digest(store, winner_ids=c.product.promo_video_ids or None),
        notes_text(store, niche, exclude_titles={LEARNING_TITLE}),
        verdicts(store, niche, top),
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


def concept_examples(store: Store, video_ids: list[str], n: int = 3) -> list[dict]:
    """The most-viewed member videos of a concept (id, author, url, latest views), so the site
    can show what a format looks like instead of only naming it."""
    if not video_ids:
        return []
    marks = ",".join("?" * len(video_ids))
    rows = store.rows(
        f"""SELECT v.id, v.author, v.url, v.duration,
                   (SELECT o.views FROM observations o WHERE o.video_id=v.id
                    ORDER BY o.observed_at DESC LIMIT 1) AS views
            FROM videos v WHERE v.id IN ({marks})""",
        tuple(video_ids),
    )
    rows.sort(key=lambda r: r["views"] or 0, reverse=True)
    return rows[:n]


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


def pick_shares(concepts: list[dict], draws: int = 4000, seed: int = 0) -> list[float]:
    """How often each concept would win the picker's draw, by simulating it `draws` times with a
    fixed seed. Same noise as pick(): EXPLORE_SD shrinking with the concept's own post count."""
    if not concepts:
        return []
    rng = random.Random(seed)
    wins = [0] * len(concepts)
    for _ in range(draws):
        best, best_i = -1e9, 0
        for i, c in enumerate(concepts):
            x = rng.gauss(c["prior"] + c["learned"], EXPLORE_SD / math.sqrt(1 + c["n"]))
            if x > best:
                best, best_i = x, i
        wins[best_i] += 1
    return [w / draws for w in wins]


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
        try:
            c["examples"] = concept_examples(store, json.loads(c.pop("video_ids", None) or "[]"))
        except ValueError:
            c["examples"] = []
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


def propose_batch(store: Store, niche: str, formats: int = 3) -> list[dict]:
    """The formats the next batch of scripts should span: the `formats` concepts the picker
    chooses most often, each with the reasons a reader can check. One format per cycle made every
    batch look alike (five scripts, one format, all "demo 5/5"); spreading the batch over the
    picker's top choices tests more than one idea per cycle while still favouring what the
    evidence favours. `expected_lift` is what the picker believes the format earns beyond its
    head start: trait evidence from our posts and the niche, taken over by its own posts as they
    come in (log10; +1 is 10x)."""
    cands = concept_scores(store, niche)
    if not cands:
        return []
    for c, share in zip(cands, pick_shares(cands), strict=False):
        c["pick_share"] = round(share, 3)
    cands.sort(key=lambda c: (-c["pick_share"], -(c["prior"] + c["learned"])))
    out = []
    for c in cands[:formats]:
        out.append(
            {
                **c,
                "why": {
                    "pick_share": c["pick_share"],
                    "head_start": c["prior"],
                    "expected_lift": c["learned"],
                    "own_mean_reward": c["mean_reward"],
                    "own_n": c["n"],
                    "traits": c["trait_detail"],
                    "kind": c["kind"],
                },
            }
        )
    return out


def rank_scripts(rows: list[dict]) -> list[dict]:
    """Scripts best first: by the expected lift of their format, then the writer's demo score,
    then id. The demo score is the writer grading its own script on whether the product shows
    within 5s; it gates a script, it does not predict views."""

    def lift(r: dict) -> float:
        why = r.get("why")
        if why is None:
            try:
                why = json.loads(r.get("payload") or "{}").get("why") or {}
            except ValueError:
                why = {}
        return float(why.get("expected_lift") or 0.0)

    return sorted(rows, key=lambda r: (-lift(r), -(r.get("demo_score") or 0), r.get("id") or 0))
