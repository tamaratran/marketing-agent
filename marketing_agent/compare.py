"""Our posts next to the market. For each hook type, visual style and concept: mean lift over
the account's usual views on reference videos and on our posts. Each side is still scored on its
own group; this only lines the two up so differences are visible."""

from .scoreboard import build, rank_by
from .store import Store

TRAITS = (("hook", "hook_type"), ("style", "visual_style"), ("concept", "concept"))
MARKET_MIN_N = 2


def _verdict(market: float | None, ours: float | None) -> str:
    if market is None:
        return "only we tried it"
    if ours is None:
        return "untried by us" if market > 0 else "loses in market, untried by us"
    if market > 0 and ours <= 0:
        return "works in market, not for us"
    if market <= 0 and ours > 0:
        return "works for us, not in market"
    return "works for both" if market > 0 else "loses for both"


_ORDER = (
    "works in market, not for us",
    "works for us, not in market",
    "untried by us",
    "works for both",
    "only we tried it",
    "loses for both",
    "loses in market, untried by us",
)


def compare(store: Store, tag: str | None = None) -> list[dict]:
    """One row per trait value seen on either side, most useful first: disagreements, then
    market winners we haven't tried. Our side counts a single post (we have few)."""
    market = build(store, tag, group="reference")["videos"]
    ours = build(store, group="ours")["videos"]
    rows = []
    for kind, key in TRAITS:
        m = {r[key]: r for r in rank_by(market, key, min_n=MARKET_MIN_N)}
        o = {r[key]: r for r in rank_by(ours, key, min_n=1)}
        for value in set(m) | set(o):
            mr, orr = m.get(value), o.get(value)
            rows.append(
                {
                    "trait": kind,
                    "value": value,
                    "market": mr["mean_reward"] if mr else None,
                    "market_n": mr["n"] if mr else 0,
                    "ours": orr["mean_reward"] if orr else None,
                    "ours_n": orr["n"] if orr else 0,
                }
            )
    for r in rows:
        r["verdict"] = _verdict(r["market"], r["ours"])
    return sorted(
        rows,
        key=lambda r: (_ORDER.index(r["verdict"]), -abs((r["market"] or 0) - (r["ours"] or 0))),
    )


def compare_text(store: Store, tag: str | None = None, top: int = 4) -> str:
    """Script-prompt lines: where our results disagree with the market, and market winners we
    haven't tried yet. Empty when neither exists."""

    def fmt(x: float | None) -> str:
        return "-" if x is None else f"{x:+.2f}"

    keep = ("works in market, not for us", "works for us, not in market", "untried by us")
    picked = [r for r in compare(store, tag) if r["verdict"] in keep][:top]
    if not picked:
        return ""
    return "Our posts vs the market (lift over each account's usual views):\n" + "\n".join(
        f"{r['trait']} {r['value']}: market {fmt(r['market'])} (n={r['market_n']}), "
        f"ours {fmt(r['ours'])} (n={r['ours_n']}): {r['verdict']}"
        for r in picked
    )
