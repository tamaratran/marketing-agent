"""Static HTML dashboard rendered straight from the db. No server: `mkt daily` writes it next to the
report, the daily session pushes it to the state branch, Vercel serves the branch."""

import html
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

from .policy import concept_scores, winning_traits
from .scoreboard import build
from .store import Store

CSS = """
:root{--fg:#111;--mut:#666;--line:#e6e6e6;--bg:#fff;--acc:#0a7;--bad:#c33}
*{box-sizing:border-box}body{margin:0;font:15px/1.45 -apple-system,Inter,Segoe UI,sans-serif;color:var(--fg);background:var(--bg)}
main{max-width:1100px;margin:0 auto;padding:32px 20px 80px}h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:36px 0 10px}
.sub{color:var(--mut);margin:0 0 20px}.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.kpi{border:1px solid var(--line);border-radius:10px;padding:12px 14px}.kpi b{display:block;font-size:22px}.kpi span{color:var(--mut);font-size:13px}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mut);font-weight:500;font-size:12px;text-transform:uppercase;letter-spacing:.03em}td.n{text-align:right;font-variant-numeric:tabular-nums}th.n{text-align:right}
.pos{color:var(--acc)}.neg{color:var(--bad)}.mut{color:var(--mut)}a{color:inherit}
.clips{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:14px}.clip video{width:100%;border-radius:10px;background:#000;aspect-ratio:9/16}
.clip p{margin:6px 0 0;font-size:13px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:24px}@media(max-width:800px){.grid2{grid-template-columns:1fr}}
.tag{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:1px 8px;font-size:12px;color:var(--mut);margin-right:4px}
"""


def _e(x) -> str:
    return html.escape("" if x is None else str(x))


def _reward(r) -> str:
    if r is None:
        return '<span class="mut">-</span>'
    cls = "pos" if r > 0 else "neg" if r < 0 else ""
    return f'<span class="{cls}">{r:+.2f}</span>'


def _table(headers: list[tuple[str, bool]], rows: list[list[str]]) -> str:
    th = "".join(f'<th class="{"n" if n else ""}">{_e(h)}</th>' for h, n in headers)
    body = ""
    for row in rows:
        body += (
            "<tr>"
            + "".join(
                f'<td class="{"n" if headers[i][1] else ""}">{c}</td>' for i, c in enumerate(row)
            )
            + "</tr>"
        )
    return f"<table><thead><tr>{th}</tr></thead><tbody>{body or '<tr><td class=mut>none yet</td></tr>'}</tbody></table>"


def render(store: Store, niche: str, out: Path, copy_assets: bool = True) -> Path:
    """Write index.html (and copy referenced clips into out.parent/renders when copy_assets)."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sb = build(store)
    now = int(time.time())
    week = now - 7 * 86400

    scripts = store.rows(
        """SELECT s.id, s.hook, s.demo_score, s.created_at, s.product, c.name concept FROM scripts s
           LEFT JOIN concepts c ON c.id=s.concept_id WHERE s.created_at>=?
           ORDER BY s.created_at DESC, s.demo_score DESC LIMIT 40""",
        (week,),
    )
    renders = store.rows(
        """SELECT r.id, r.script_id, r.final_path, r.cost_usd, r.model, r.created_at, s.hook
           FROM renders r JOIN scripts s ON s.id=r.script_id
           WHERE r.final_path IS NOT NULL ORDER BY r.created_at DESC LIMIT 12"""
    )
    clips = []
    seen = set()
    for r in renders:
        if r["final_path"] in seen:
            continue
        seen.add(r["final_path"])
        src = Path(r["final_path"])
        rel = None
        if copy_assets and src.exists():
            dst = out.parent / "renders" / src.name
            dst.parent.mkdir(exist_ok=True)
            if not dst.exists() or dst.stat().st_size != src.stat().st_size:
                shutil.copyfile(src, dst)
            rel = f"renders/{src.name}"
        elif (out.parent / "renders" / src.name).exists():
            rel = f"renders/{src.name}"
        if rel:
            clips.append((rel, r))
    cs = concept_scores(store, niche)
    traits = winning_traits(store)
    spent = sum(r["cost_usd"] or 0 for r in store.rows("SELECT cost_usd FROM renders"))

    kpis = [
        (len(sb["videos"]), "reference videos tracked"),
        (sb["n_scored"], "scored"),
        (sb["n_tagged"], "tagged by classifier"),
        (len(cs), "concepts"),
        (len(scripts), "scripts this week"),
        (f"${spent:.2f}", "spent on renders"),
    ]
    kpi_html = "".join(f"<div class=kpi><b>{_e(v)}</b><span>{_e(k)}</span></div>" for v, k in kpis)

    def rank_table(key, rows):
        return _table(
            [(key.replace("_", " "), False), ("n", True), ("mean reward", True), ("win", True)],
            [
                [_e(r[key]), str(r["n"]), _reward(r["mean_reward"]), f"{r['win_rate']:.0%}"]
                for r in rows[:8]
            ],
        )

    concept_table = _table(
        [("concept", False), ("early", True), ("prior", True), ("observed", True), ("n", True)],
        [
            [
                _e(c["name"]),
                f"{c['early_score'] or 0:.0f}",
                f"{c['prior']:.2f}",
                _reward(c["mean_reward"]),
                str(c["n"]),
            ]
            for c in cs[:12]
        ],
    )
    script_rows = [
        [
            f"s{s['id']}",
            _e(s["hook"]),
            f"<span class=tag>{_e(s['concept'])}</span>",
            str(s["demo_score"]),
            datetime.fromtimestamp(s["created_at"], UTC).strftime("%b %d"),
        ]
        for s in scripts
    ]
    scripts_table = _table(
        [("id", False), ("hook", False), ("concept", False), ("demo", True), ("day", False)],
        script_rows,
    )
    clips_html = (
        "".join(
            f'<div class=clip><video src="{_e(rel)}" controls muted playsinline preload="metadata"></video>'
            f"<p>s{r['script_id']} · ${r['cost_usd'] or 0:.2f}<br><span class=mut>{_e(r['hook'])}</span></p></div>"
            for rel, r in clips
        )
        or "<p class=mut>no clips yet</p>"
    )
    videos_table = _table(
        [
            ("reward", True),
            ("views", True),
            ("hook", False),
            ("concept", False),
            ("author", False),
            ("", False),
        ],
        [
            [
                _reward(v["reward"]),
                f"{v['views']:,}",
                _e(v.get("hook_type") or ""),
                _e((v.get("concept") or "")[:40]),
                _e(v["author"]),
                f'<a href="{_e(v["url"])}" target=_blank rel=noopener>open</a>',
            ]
            for v in [x for x in sb["videos"] if x.get("hook_type")][:20]
        ],
    )
    stuck = (
        ", ".join(_e(f["author"]) for f in build(store, group="ours")["stuck_accounts"]) or "none"
    )

    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>marketing agent · {_e(niche)}</title>
<style>{CSS}</style></head><body><main>
<h1>marketing agent · {_e(niche)}</h1>
<p class=sub>updated {datetime.fromtimestamp(now, UTC):%Y-%m-%d %H:%M} UTC · read-only, rebuilt by the daily run</p>
<div class=kpis>{kpi_html}</div>
<h2>What is working (reference videos)</h2>
<p class=mut>{_e(traits) or "Nothing scored yet; picks follow the radar's early score."}</p>
<div class=grid2><div>{rank_table("hook_type", sb["hooks"])}</div><div>{rank_table("visual_style", sb["styles"])}</div></div>
<h2>Concepts (what tomorrow picks from)</h2>{concept_table}
<h2>Clips</h2><div class=clips>{clips_html}</div>
<h2>Scripts this week</h2>{scripts_table}
<h2>Top tagged videos in the niche</h2>{videos_table}
<p class=mut>Possibly throttled accounts: {stuck}</p>
</main></body></html>"""
    out.write_text(page)
    return out
