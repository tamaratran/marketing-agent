"""Analysis layer: what do the videos that beat their creator's baseline have in common, once
the obvious confounders are held fixed.

Panel = the feature rows from `cohort.build_features`. Outcome = `lift_72h` (log10 views at 72h
minus the creator's baseline log views). Each trait (hook type, visual style, product by 5s,
pacing, duration, posting hour) is fit with ordinary least squares against the outcome with the
controls as dummy columns; the coefficient per level is the controlled effect relative to the
most common level, with a 95% interval and the raw (uncontrolled) mean beside it. Pure Python on
purpose: a few thousand rows and a few dozen columns solve in milliseconds and the API image
stays small.

Honesty rules live here, not in the UI: cells under MIN_N are `thin`, intervals that cross zero
are `no evidence`, and a trait only `travels` across niches when the pooled and per-niche fits
agree in sign with both intervals clear of zero."""

from __future__ import annotations

import json
import math
import statistics
import time
from collections import Counter

from .cohort import features
from .store import Store

MIN_N = 20
TRAITS = [
    "hook_type",
    "visual_style",
    "product_on_screen_by_5s",
    "pacing_bucket",
    "duration_bucket",
    "posted_hour_bucket",
]
CONTROLS = ["niche", "follower_bucket", "duration_bucket", "posted_hour_bucket"]
OUTCOMES = {
    "lift_now": "lift over niche videos of the same age and account size, at the latest check (log10)",
    "lift_72h": "lift over the creator's baseline at 72h (log10)",
    "growth_6_24": "6h to 24h growth (log10 ratio)",
    "log_vph_6h": "views per hour at 6h (log10)",
}


DEFAULT_OUTCOME = "lift_now"


def _outcome(row: dict, name: str) -> float | None:
    if name == "log_vph_6h":
        v = row.get("vph_6h")
        return math.log10(v) if v else None
    return row.get(name)


def _solve(xtx: list[list[float]], xty: list[float]) -> list[float]:
    """Gaussian elimination with a tiny ridge so collinear dummies do not blow up."""
    n = len(xty)
    a = [row[:] + [xty[i]] for i, row in enumerate(xtx)]
    for i in range(n):
        a[i][i] += 1e-6
    for i in range(n):
        p = max(range(i, n), key=lambda r: abs(a[r][i]))
        a[i], a[p] = a[p], a[i]
        if abs(a[i][i]) < 1e-12:
            continue
        for r in range(n):
            if r != i and a[r][i]:
                f = a[r][i] / a[i][i]
                for c in range(i, n + 1):
                    a[r][c] -= f * a[i][c]
    return [a[i][n] / a[i][i] if abs(a[i][i]) > 1e-12 else 0.0 for i in range(n)]


def _design(
    rows: list[dict], trait: str, controls: list[str]
) -> tuple[list[list[float]], list[str]]:
    """Dummy-code trait and controls; the most common level of each is the reference."""
    cols: list[str] = ["intercept"]
    levels: dict[str, list] = {}
    for var in [trait, *controls]:
        if var == trait or var not in (trait,):
            counts = Counter(str(r.get(var)) for r in rows)
            ordered = [lvl for lvl, _ in counts.most_common()]
            levels[var] = ordered[1:]
            cols += [f"{var}={lvl}" for lvl in ordered[1:]]
    x = []
    for r in rows:
        row = [1.0]
        for var in [trait, *controls]:
            row += [1.0 if str(r.get(var)) == lvl else 0.0 for lvl in levels[var]]
        x.append(row)
    return x, cols


def ols(rows: list[dict], outcome: str, trait: str, controls: list[str]) -> dict:
    """Controlled effect of each trait level on the outcome, relative to the trait's most common
    level. Returns per-level coef, se, 95% interval, n, raw mean, and the fit's n and r2."""
    controls = [c for c in controls if c != trait]
    data = [r for r in rows if _outcome(r, outcome) is not None and r.get(trait) is not None]
    if len(data) < 3:
        return {"n": len(data), "levels": []}
    y = [_outcome(r, outcome) for r in data]
    x, cols = _design(data, trait, controls)
    k = len(cols)
    xtx = [[sum(xi[a] * xi[b] for xi in x) for b in range(k)] for a in range(k)]
    xty = [sum(xi[a] * yi for xi, yi in zip(x, y, strict=True)) for a in range(k)]
    beta = _solve(xtx, xty)
    resid = [
        yi - sum(b * v for b, v in zip(beta, xi, strict=True)) for xi, yi in zip(x, y, strict=True)
    ]
    dof = max(len(data) - k, 1)
    sigma2 = sum(e * e for e in resid) / dof
    inv = [_solve(xtx, [1.0 if i == j else 0.0 for i in range(k)]) for j in range(k)]
    ybar = statistics.fmean(y)
    sst = sum((yi - ybar) ** 2 for yi in y) or 1.0
    r2 = 1 - sum(e * e for e in resid) / sst
    counts = Counter(str(r.get(trait)) for r in data)
    ref = counts.most_common(1)[0][0]
    raw = {
        lvl: statistics.fmean(_outcome(r, outcome) for r in data if str(r.get(trait)) == lvl)
        for lvl in counts
    }
    out = [
        {
            "level": ref,
            "n": counts[ref],
            "coef": 0.0,
            "se": 0.0,
            "lo": 0.0,
            "hi": 0.0,
            "raw_mean": round(raw[ref], 3),
            "reference": True,
            "verdict": "reference",
        }
    ]
    for j, col in enumerate(cols):
        if not col.startswith(f"{trait}="):
            continue
        lvl = col.split("=", 1)[1]
        se = math.sqrt(max(sigma2 * inv[j][j], 0.0))
        lo, hi = beta[j] - 1.96 * se, beta[j] + 1.96 * se
        n = counts[lvl]
        verdict = (
            "thin"
            if n < MIN_N or counts[ref] < MIN_N
            else ("no evidence" if lo <= 0 <= hi else ("better" if beta[j] > 0 else "worse"))
        )
        out.append(
            {
                "level": lvl,
                "n": n,
                "coef": round(beta[j], 3),
                "se": round(se, 3),
                "lo": round(lo, 3),
                "hi": round(hi, 3),
                "raw_mean": round(raw[lvl], 3),
                "reference": False,
                "verdict": verdict,
            }
        )
    return {"n": len(data), "k": k, "r2": round(r2, 3), "reference": ref, "levels": out}


def analyze(store: Store, niches: list[str] | None = None) -> dict:
    """Pooled and per-niche fits for every trait and outcome, plus a status block that says how
    much of the panel has reached each age, so the UI can say 'collecting' instead of showing
    thin numbers. Reference videos only; our posts are judged in own.own_posts."""
    from . import campaign as campaign_cfg
    from .scoreboard import build

    niches = niches or [campaign_cfg.load().niche.name]
    rows = [r for r in features(store, group="reference") if r["niche"] in niches]
    # The outcome that exists at cycle time: how each video sits against niche videos of the same
    # age from accounts of the same size (scoreboard.rewards), once it is a day old. The 72h
    # outcomes keep filling in behind it as the panel ages.
    reward: dict[str, float] = {}
    for n in niches:
        for v in build(store, tags=store.niche_tags(n) or None, group="reference")["videos"]:
            if v.get("reward") is not None:
                reward[v["id"]] = v["reward"]
    for r in rows:
        r["lift_now"] = reward.get(r["video_id"])
    now = int(time.time())
    reached = {f"{a}h": sum(1 for r in rows if r.get(f"views_{a}h")) for a in (1, 6, 24, 72, 168)}
    reached["scored"] = sum(1 for r in rows if r.get("lift_now") is not None)
    first_72h = min((r for r in rows), key=lambda r: -r["age_h"], default=None)
    eta_72h = None
    if rows and reached["72h"] == 0:
        oldest_age = max(r["age_h"] for r in rows)
        eta_72h = now + int(max(72 - oldest_age, 0) * 3600)
    out = {
        "built_at": now,
        "status": {
            "videos": len(rows),
            "tagged": sum(1 for r in rows if r.get("tagged")),
            "with_baseline": sum(1 for r in rows if r.get("creator_baseline_log") is not None),
            "reached": reached,
            "eta_72h": eta_72h,
            "niches": {n: sum(1 for r in rows if r["niche"] == n) for n in niches},
        },
        "outcomes": OUTCOMES,
        "min_n": MIN_N,
        "fits": {},
    }
    del first_72h
    for outcome in OUTCOMES:
        out["fits"][outcome] = {"pooled": {}, "per_niche": {}}
        for trait in TRAITS:
            pooled = ols(rows, outcome, trait, CONTROLS)
            per = {
                n: ols(
                    [r for r in rows if r["niche"] == n],
                    outcome,
                    trait,
                    [c for c in CONTROLS if c != "niche"],
                )
                for n in niches
            }
            for lvl in pooled.get("levels", []):
                if lvl["reference"]:
                    continue
                signs = []
                for n in niches:
                    m = next(
                        (x for x in per[n].get("levels", []) if x["level"] == lvl["level"]), None
                    )
                    if m and m["verdict"] in ("better", "worse"):
                        signs.append(m["verdict"])
                lvl["travels"] = (
                    bool(signs)
                    and len(set(signs)) == 1
                    and lvl["verdict"] == signs[0]
                    and len(signs) == len(niches) > 1
                )
            out["fits"][outcome]["pooled"][trait] = pooled
            out["fits"][outcome]["per_niche"][trait] = per
    return out


def save_findings(store: Store, result: dict) -> None:
    with store.conn() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS findings (built_at INTEGER PRIMARY KEY, payload TEXT)"
        )
        c.execute(
            "INSERT OR REPLACE INTO findings VALUES (?, ?)",
            (result["built_at"], json.dumps(result)),
        )


def latest_findings(store: Store) -> dict | None:
    with store.conn() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS findings (built_at INTEGER PRIMARY KEY, payload TEXT)"
        )
        row = c.execute("SELECT payload FROM findings ORDER BY built_at DESC LIMIT 1").fetchone()
    return json.loads(row[0]) if row else None


def controlled_lift(store: Store, trait: str, outcome: str = DEFAULT_OUTCOME) -> dict[str, dict]:
    """For the picker: level -> {coef, se, n, verdict} from the latest pooled fit, empty when
    nothing has been analysed or the panel is still collecting."""
    f = latest_findings(store)
    if not f:
        return {}
    fit = f["fits"].get(outcome, {}).get("pooled", {}).get(trait, {})
    return {lvl["level"]: lvl for lvl in fit.get("levels", [])}
