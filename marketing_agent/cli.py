"""`mkt` CLI. Pipeline: scrape -> download -> classify -> concepts -> scripts -> render. `run` chains them."""

import json
import time
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from .config import settings
from .store import Store

console = Console()


def _store() -> Store:
    return Store(settings.db_path)


@click.group()
def cli():
    """Marketing agent: research, classify, generate."""


@cli.command()
@click.argument("tags", nargs=-1, required=True)
@click.option("--scrolls", default=3)
def scrape(tags, scrolls):
    """Pull fresh videos for hashtags from TikTok (browser via CDP) into the store."""
    from .research.tiktok_browser import scrape_hashtag_sync

    store = _store()
    for tag in tags:
        rows = scrape_hashtag_sync(tag.lstrip("#"), settings.cdp_url, scrolls)
        for r in rows:
            store.upsert_video(r)
        console.print(f"#{tag}: {len(rows)} videos")


@cli.command()
@click.option("--tag", default=None)
@click.option("--max-age-h", default=72)
@click.option("--limit", default=25)
def radar(tag, max_age_h, limit):
    """Rank stored videos by early-traction score."""
    from .research.radar import rank

    rows = rank(_store(), tag, max_age_h, limit)
    t = Table("score", "age h", "views", "followers", "dur", "sound", "caption", "url")
    for r in rows:
        t.add_row(
            str(r["early_score"]),
            str(r["age_h"]),
            str(r["views"]),
            str(r["followers"]),
            str(r["duration"]),
            (r["music"] or "")[:20],
            (r["desc"] or "")[:50],
            r["url"],
        )
    console.print(t)


@cli.command()
@click.option("--tag", default=None)
@click.option("--top", default=10, help="Download the top N by early score")
@click.option("--max-age-h", default=72)
def download(tag, top, max_age_h):
    """Download top-ranked videos for the classifier."""
    from .research.radar import rank
    from .research.tiktok_browser import fetch_video_sync

    store = _store()
    for r in rank(store, tag, max_age_h, top):
        if r.get("local_path") and Path(r["local_path"]).exists():
            continue
        out = settings.videos_dir / f"{r['id']}.mp4"
        try:
            fetch_video_sync(r["url"], out, settings.cdp_url)
        except Exception as e:
            console.print(f"[red]{r['id']}: {e}")
            continue
        store.set_local_path(r["id"], str(out))
        console.print(f"saved {out} ({out.stat().st_size // 1024} KB)")


@cli.command()
@click.option("--limit", default=20)
@click.option("--model", default=None)
def classify(limit, model):
    """Tag downloaded, untagged videos with the multimodal classifier."""
    from .classifier.classify import classify as run_classify

    store = _store()
    model = model or settings.openai_model
    for v in store.untagged(limit):
        v["hashtags"] = json.loads(v["hashtags"] or "[]")
        res = run_classify(
            Path(v["local_path"]), v, model=model, transcribe_model=settings.transcribe_model
        )
        store.save_tags(v["id"], model, res)
        tg = res["tags"]
        console.print(
            f"{v['id']} {res['run']['latency_s']}s  {tg['hook_type']:>15} | {tg['visual_style']:>18} | "
            f"demo {tg['demo_score_1_5']} | {tg['concept'][:70]}"
        )


@cli.command()
@click.argument("niche")
@click.option("--tag", default=None)
@click.option("--max-age-h", default=72)
@click.option("--limit", default=40)
def concepts(niche, tag, max_age_h, limit):
    """Cluster ranked videos into reusable concepts and store them."""
    from .research.radar import cluster, rank

    store = _store()
    out = cluster(store, niche, rank(store, tag, max_age_h, limit), settings.openai_model)
    t = Table("id", "early", "n", "top views", "concept", "hook pattern")
    for c in out:
        t.add_row(
            str(c["id"]),
            str(c["early_score"]),
            str(c["n"]),
            str(c["top_views"]),
            f"{c['name']}: {c['description'][:60]}",
            c.get("hook_pattern", "")[:50],
        )
    console.print(t)


@cli.command()
@click.argument("concept_id", type=int)
@click.argument("product")
@click.option("-n", default=12)
@click.option("--min-score", default=3)
def scripts(concept_id, product, n, min_score):
    """Write N remix scripts for a concept and a product; drop ones that don't demo in 5s."""
    from .video.scripts import write_scripts

    store = _store()
    rows = store.rows("SELECT * FROM concepts WHERE id=?", (concept_id,))
    if not rows:
        raise click.ClickException(f"no concept {concept_id}")
    c = {**json.loads(rows[0]["payload"]), "id": concept_id}
    out = write_scripts(store, c, product, n, min_score, settings.openai_model)
    for s in out:
        mark = "keep" if s["kept"] else "drop"
        console.print(
            f"[{mark}] #{s['id']} demo {s['demo_score_1_5']} reveal {s['product_reveal_s']}s  {s['hook']}"
        )


@cli.command()
@click.argument("script_ids", nargs=-1, type=int, required=True)
@click.option("--provider", default=None, help="replicate (default) or stub")
@click.option("--duration", default=10)
@click.option("--sound", type=click.Path(exists=True), default=None)
@click.option("--ref", multiple=True, help="Reference image path/URL (product, creator)")
def render(script_ids, provider, duration, sound, ref):
    """Generate a clip per script with Seedance and cut a captioned 1080x1920 video."""
    from .video.edit import assemble, captions_from_script, probe_duration
    from .video.generate import GenRequest, get_provider

    store = _store()
    prov = get_provider(provider)
    for sid in script_ids:
        rows = store.rows("SELECT * FROM scripts WHERE id=?", (sid,))
        if not rows:
            console.print(f"[red]no script {sid}")
            continue
        s = json.loads(rows[0]["payload"])
        raw = settings.renders_dir / f"s{sid}_raw.mp4"
        final = settings.renders_dir / f"s{sid}.mp4"
        t0 = time.time()
        res = prov.generate(
            GenRequest(prompt=s["video_prompt"], duration_s=duration, reference_images=list(ref)),
            raw,
        )
        caps = captions_from_script(s["hook"], s["body"], probe_duration(raw))
        assemble([raw], final, captions=caps, sound=Path(sound) if sound else None)
        store.insert(
            "renders",
            {
                "script_id": sid,
                "created_at": int(time.time()),
                "model": res.model,
                "prompt": s["video_prompt"],
                "raw_path": str(raw),
                "final_path": str(final),
                "cost_usd": res.cost_usd,
                "payload": json.dumps(res.raw, default=str),
            },
        )
        console.print(
            f"script {sid}: {final} ({res.model}, ${res.cost_usd}, {round(time.time() - t0)}s)"
        )


@cli.command()
@click.argument("urls", nargs=-1, required=True)
def poll(urls):
    """Record current public stats for video URLs (scoreboard input, no browser needed)."""
    from .research.tiktok_browser import poll_public_stats

    store = _store()
    for u in urls:
        row = poll_public_stats(u)
        if not row:
            console.print(f"[red]no data for {u}")
            continue
        store.upsert_video(row)
        console.print(
            f"{row['id']}: {row['views']} views, {row['likes']} likes, {row['shares']} shares"
        )


@cli.command()
@click.option("--tag", default=None)
def scoreboard(tag):
    """Views over time plus classifier tags, so hooks/concepts can be ranked."""
    store = _store()
    rows = store.latest(tag, limit=200)
    tags = store.tags_for([r["id"] for r in rows])
    t = Table("views", "likes", "shares", "obs", "hook", "style", "concept", "url")
    for r in sorted(rows, key=lambda r: -(r["views"] or 0))[:40]:
        n_obs = store.rows("SELECT COUNT(*) c FROM observations WHERE video_id=?", (r["id"],))[0][
            "c"
        ]
        tg = tags.get(r["id"], {}).get("tags", {})
        t.add_row(
            str(r["views"]),
            str(r["likes"]),
            str(r["shares"]),
            str(n_obs),
            tg.get("hook_type", ""),
            tg.get("visual_style", ""),
            tg.get("concept", "")[:50],
            r["url"],
        )
    console.print(t)


@cli.command()
@click.argument("niche")
@click.argument("tags", nargs=-1, required=True)
@click.option("--product", default=None, help="If set, also write scripts for the top concept")
@click.option("--top", default=8)
@click.pass_context
def run(ctx, niche, tags, product, top):
    """Daily loop: scrape -> download top -> classify -> concepts (-> scripts)."""
    ctx.invoke(scrape, tags=tags, scrolls=3)
    ctx.invoke(download, tag=None, top=top, max_age_h=72)
    ctx.invoke(classify, limit=top, model=None)
    ctx.invoke(concepts, niche=niche, tag=None, max_age_h=72, limit=40)
    if product:
        store = _store()
        best = store.rows(
            "SELECT id FROM concepts WHERE niche=? ORDER BY created_at DESC, early_score DESC LIMIT 1",
            (niche,),
        )
        if best:
            ctx.invoke(scripts, concept_id=best[0]["id"], product=product, n=12, min_score=3)


if __name__ == "__main__":
    cli()
