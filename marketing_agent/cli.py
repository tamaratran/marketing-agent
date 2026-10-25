"""`mkt` CLI. Pipeline: scrape -> download -> classify -> concepts -> scripts -> render -> creators -> scoreboard.
`run` chains the research half."""

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
@click.argument("tags", nargs=-1, required=True)
@click.option("--scrolls", default=6)
@click.option("--max-classify", default=100, help="Cohort videos to download and tag this run")
def cohort(niche, tags, scrolls, max_classify):
    """Enroll fresh videos (<6h old) from the niche's hashtags as a cohort, snapshot their
    creators, download and tag all of them, and build the feature rows. Repoll keeps the curves."""
    from .cohort import build_features, enroll, snapshot_creator
    from .research.tiktok_browser import profile_stats, scrape_hashtag_sync

    store = _store()
    store.set_niche_tags(niche, list(tags))
    fresh: list[dict] = []
    for tag in tags:
        rows = scrape_hashtag_sync(tag, settings.cdp_url, scrolls=scrolls)
        for r in rows:
            store.upsert_video(r)
        got = enroll(store, niche, rows)
        fresh += got
        console.print(f"#{tag}: {len(rows)} seen, {len(got)} fresh enough for the cohort")
    for author in sorted({r["author"] for r in fresh if r.get("author")}):
        try:
            stats = profile_stats(author)
        except Exception as e:  # noqa: BLE001 - a missing baseline must not stop the run
            console.print(f"[yellow]profile @{author}: {e!r}")
            stats = None
        snap = snapshot_creator(store, author, stats=stats)
        console.print(
            f"@{author}: {snap['followers']} followers, {snap['video_count']} posts, "
            f"{snap['n_posts']} in db (median {snap['median_views']} views)"
        )
    ctx = click.get_current_context()
    cohort_ids = {r["id"] for r in fresh}
    from .research.tiktok_browser import fetch_video_sync

    n = 0
    for v in store.rows(
        "SELECT * FROM videos WHERE cohort_at IS NOT NULL AND local_path IS NULL ORDER BY cohort_at DESC"
    ):
        if n >= max_classify:
            break
        out = settings.videos_dir / f"{v['id']}.mp4"
        try:
            fetch_video_sync(v["url"], out, settings.cdp_url)
            store.set_local_path(v["id"], str(out))
            n += 1
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]{v['id']}: {e!r}")
    ctx.invoke(classify, limit=max_classify, model=None)
    console.print(f"features: {build_features(store, niche)} rows ({len(cohort_ids)} new today)")


@cli.command()
@click.option("--max-age-days", default=8.0)
@click.option("--niche", default=None)
def repoll(max_age_days, niche):
    """Re-record public stats for every cohort video still inside the window, then rebuild
    features. No browser needed; this is what the 2-hourly cron runs."""
    from .cohort import build_features
    from .cohort import repoll as do_repoll

    store = _store()
    res = do_repoll(store, max_age_days, niche)
    res["features"] = build_features(store, niche)
    console.print(res)


@cli.command()
@click.argument("niche")
@click.option("--tag", default=None)
@click.option("--max-age-h", default=72)
@click.option("--limit", default=40)
def concepts(niche, tag, max_age_h, limit):
    """Cluster ranked videos into reusable concepts and store them."""
    from .research.radar import cluster, rank

    store = _store()
    ranked = rank(store, tag, max_age_h, limit)
    niche_tags = store.niche_tags(niche)
    if not tag and niche_tags:
        ranked = [r for r in ranked if r["source_tag"] in niche_tags]
    out = cluster(store, niche, ranked, settings.openai_model)
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
    from .policy import winning_traits

    out = write_scripts(
        store, c, product, n, min_score, settings.openai_model, winning_traits(store)
    )
    for s in out:
        mark = "keep" if s["kept"] else "drop"
        console.print(
            f"[{mark}] #{s['id']} demo {s['demo_score_1_5']} reveal {s['product_reveal_s']}s  {s['hook']}"
        )


@cli.command()
@click.argument("script_ids", nargs=-1, type=int, required=True)
@click.option(
    "--provider",
    default=None,
    help="fal (default, Seedance 2.5), replicate (Seedance 2.0 fast) or stub",
)
@click.option("--duration", default=12, help="Seconds of generated video")
@click.option("--resolution", default="720p", help="480p, 720p or 1080p")
@click.option("--sound", type=click.Path(exists=True), default=None)
@click.option("--ref", multiple=True, help="Reference image path/URL (product, creator)")
def render(script_ids, provider, duration, resolution, sound, ref):
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
            GenRequest(
                prompt=s["video_prompt"],
                duration_s=duration,
                resolution=resolution,
                reference_images=list(ref),
            ),
            raw,
        )
        caps = captions_from_script(s["hook"], s.get("captions") or [], probe_duration(raw))
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
@click.option("--top", default=25)
def scoreboard(tag, top):
    """Reward per video (log views vs the account's baseline), hooks and concepts ranked by it,
    and accounts stuck under 1k views."""
    from .scoreboard import build, growth

    store = _store()
    sb = build(store, tag)
    console.print(
        f"{len(sb['videos'])} videos, {sb['n_scored']} old enough to score, {sb['n_tagged']} tagged"
    )
    t = Table("reward", "views", "vph now", "eng/1k", "hook", "concept", "author", "url")
    for r in sb["videos"][:top]:
        g = growth(store, r["id"])
        t.add_row(
            "" if r["reward"] is None else f"{r['reward']:+.2f}",
            str(r["views"]),
            "" if not g else str(g["vph_recent"]),
            str(r["engagement_per_1k"]),
            r.get("hook_type") or "",
            (r.get("concept") or "")[:40],
            r["author"],
            r["url"],
        )
    console.print(t)
    for name, key in (("hooks", "hook_type"), ("concepts", "concept"), ("styles", "visual_style")):
        if sb[name]:
            t = Table(key, "n", "mean reward", "stderr", "win rate", title=name)
            for row in sb[name]:
                t.add_row(
                    row[key][:50],
                    str(row["n"]),
                    f"{row['mean_reward']:+.2f}",
                    f"{row['stderr']:.2f}",
                    f"{row['win_rate']:.0%}",
                )
            console.print(t)
    if sb["stuck_accounts"]:
        t = Table(
            "author", "followers", "posts", "max views", "median views", title="possibly throttled"
        )
        for f in sb["stuck_accounts"]:
            t.add_row(
                f["author"],
                str(f["followers"]),
                str(f["posts_checked"]),
                str(f["max_views"]),
                str(f["median_views"]),
            )
        console.print(t)


@cli.group()
def creators():
    """Creator ops: briefs, creator roster, posts, payouts. Drafts only, nothing is sent."""


@creators.command("brief")
@click.argument("product")
@click.argument("script_ids", nargs=-1, type=int)
@click.option("--concept", type=int, default=None, help="Use all kept scripts of this concept")
@click.option("--rate", default=1.0, help="USD per 1k views")
@click.option("--cap", default=200.0, help="Max USD per video")
@click.option("--deadline", default=5, help="Days to post")
def creators_brief(product, script_ids, concept, rate, cap, deadline):
    """Draft a paid brief from kept scripts; prints the text to paste into Discord/Sideshift."""
    from .creators.ops import create_brief

    store = _store()
    ids = list(script_ids)
    if concept is not None:
        ids += [
            r["id"]
            for r in store.rows(
                "SELECT id, payload FROM scripts WHERE concept_id=? ORDER BY demo_score DESC",
                (concept,),
            )
            if json.loads(r["payload"]).get("kept", True)
        ]
    if not ids:
        raise click.UsageError("give script ids or --concept")
    b = create_brief(store, product, ids, rate, cap, deadline)
    console.print(f"[bold]brief {b['id']} (draft, {len(b['scripts'])} scripts)[/bold]\n")
    console.print(b["body"])


@creators.command("add")
@click.argument("handle")
@click.option(
    "--channel", default="discord", help="Where they came from: discord, sideshift, clipping, dm"
)
@click.option("--rate", default=1.0)
@click.option("--followers", type=int, default=None)
@click.option("--notes", default="")
def creators_add(handle, channel, rate, followers, notes):
    from .creators.ops import add_creator

    add_creator(_store(), handle, channel, rate, followers, notes)
    console.print(f"added @{handle.lstrip('@')} at ${rate}/1k via {channel}")


@creators.command("post")
@click.argument("handle")
@click.argument("url")
@click.option("--brief", type=int, default=None)
@click.option("--script", type=int, default=None)
def creators_post(handle, url, brief, script):
    """Record that a creator posted URL; polls its public stats right away."""
    from .creators.ops import record_post
    from .research.tiktok_browser import poll_public_stats

    stats = poll_public_stats(url)
    vid = record_post(_store(), handle, url, brief, script, stats)
    console.print(
        f"post {vid} by @{handle.lstrip('@')}"
        + (f": {stats['views']} views" if stats else " (stats unavailable, poll later)")
    )


@creators.command("payouts")
@click.option("--min-age-days", default=7)
def creators_payouts(min_age_days):
    """What each post has earned (views/1k x rate, capped). Settled = older than --min-age-days."""
    from .creators.ops import payouts

    t = Table("creator", "views", "rate", "owed", "paid", "age d", "settled", "url")
    total = 0.0
    for p in payouts(_store(), min_age_days):
        total += p["owed_usd"] if p["settled"] else 0
        t.add_row(
            p["creator"],
            str(p["views"]),
            f"${p['rate_per_1k']:.2f}",
            f"${p['owed_usd']:.2f}",
            f"${p['paid_usd']:.2f}",
            str(p["age_days"]),
            "yes" if p["settled"] else "",
            p["url"],
        )
    console.print(t)
    console.print(f"settled and owed: ${total:.2f}")


@creators.command("report")
@click.option("--stall-days", default=7)
def creators_report(stall_days):
    """Who posts, who stopped."""
    from .creators.ops import creator_report

    t = Table(
        "creator", "channel", "rate", "posts", "median views", "last post", "days since", "status"
    )
    for c in creator_report(_store(), stall_days):
        style = "red" if c["status"] != "active" else ""
        t.add_row(
            c["handle"],
            c["channel"],
            f"${c['rate_per_1k']:.2f}",
            str(c["posts"]),
            str(c["median_views"]),
            c["last_post"],
            str(c["days_since"]),
            f"[{style}]{c['status']}[/{style}]" if style else c["status"],
        )
    console.print(t)


@cli.command()
@click.argument("niche")
def policy(niche):
    """What the loop has learned: winning traits and the per-concept prior/observed/sampled scores."""
    from .policy import concept_scores, winning_traits

    store = _store()
    console.print(winning_traits(store) or "[dim]nothing scored yet; picks follow early score")
    t = Table("id", "concept", "early", "prior", "observed", "n")
    for c in concept_scores(store, niche):
        t.add_row(
            str(c["id"]),
            c["name"][:40],
            f"{c['early_score'] or 0:.0f}",
            f"{c['prior']:.2f}",
            "" if c["mean_reward"] is None else f"{c['mean_reward']:+.2f}",
            str(c["n"]),
        )
    console.print(t)


@cli.command()
@click.argument("niche")
@click.argument("tags", nargs=-1, required=True)
@click.option("--product", default=None, help="If set, also write scripts for the top concept")
@click.option("--top", default=8)
@click.pass_context
def run(ctx, niche, tags, product, top):
    """Daily loop: scrape -> download top -> classify -> concepts -> pick by reward -> scripts."""
    _store().set_niche_tags(niche, list(tags))
    ctx.invoke(scrape, tags=tags, scrolls=3)
    ctx.invoke(download, tag=None, top=top, max_age_h=72)
    ctx.invoke(classify, limit=top, model=None)
    ctx.invoke(concepts, niche=niche, tag=None, max_age_h=72, limit=40)
    if product:
        from .policy import pick_concept

        best = pick_concept(_store(), niche)
        if best:
            console.print(
                f"picked concept {best['id']} '{best['name']}' (prior {best['prior']}, "
                f"observed {best['mean_reward']}, n={best['n']}, sampled {best['sampled']})"
            )
            ctx.invoke(scripts, concept_id=best["id"], product=product, n=12, min_score=3)


@cli.command()
@click.argument("niche")
@click.argument("tags", nargs=-1, required=True)
@click.option("--product", required=True)
@click.option("--top", default=8)
@click.option("--renders", default=1, help="Render the N best scripts written this run (0 = skip)")
@click.option("--resolution", default="480p")
@click.option("--report", type=click.Path(), default=None, help="Markdown report path")
@click.option(
    "--dashboard", "dashboard_out", type=click.Path(), default=None, help="index.html path"
)
@click.pass_context
def daily(ctx, niche, tags, product, top, renders, resolution, report, dashboard_out):
    """The whole loop in order with a report at the end: run (scrape, classify, concepts, pick,
    scripts), render, poll creator posts, payouts, scoreboard, policy. A failed stage is recorded
    and the rest still runs."""
    import os

    from .orchestrator import DailyReport
    from .research.tiktok_browser import poll_public_stats

    rep = DailyReport(niche, product)

    def stage(name, fn):
        t0 = time.time()
        try:
            note = fn()
            rep.ok(name, time.time() - t0, note or "")
        except Exception as e:  # noqa: BLE001 - every stage must be reported, not raised
            rep.fail(name, e)
            console.print(f"[red]{name} failed: {e!r}")

    stage("run", lambda: ctx.invoke(run, niche=niche, tags=tags, product=product, top=top))
    stage(
        "cohort",
        lambda: ctx.invoke(cohort, niche=niche, tags=tags, scrolls=6, max_classify=100),
    )
    store = _store()
    todays = [
        r["id"]
        for r in store.rows(
            "SELECT id FROM scripts WHERE product=? AND created_at>=? ORDER BY demo_score DESC, id",
            (product, int(rep.started)),
        )
    ]
    if not renders:
        rep.skip("render", "--renders 0")
    elif not todays:
        rep.skip("render", "no scripts written this run")
    elif not os.environ.get("FAL_KEY"):
        rep.skip("render", "FAL_KEY not set")
    else:
        stage(
            "render",
            lambda: ctx.invoke(
                render,
                script_ids=tuple(todays[:renders]),
                provider=None,
                duration=12,
                resolution=resolution,
                sound=None,
                ref=(),
            ),
        )

    def poll_posts():
        urls = [r["url"] for r in store.rows("SELECT url FROM posts")]
        n = 0
        for u in urls:
            row = poll_public_stats(u)
            if row:
                store.upsert_video(row)
                n += 1
        return f"{n}/{len(urls)} posts polled"

    stage("poll_posts", poll_posts)
    stage("payouts", lambda: ctx.invoke(creators_payouts, min_age_days=7))
    stage("creators", lambda: ctx.invoke(creators_report, stall_days=7))
    stage("scoreboard", lambda: ctx.invoke(scoreboard, tag=None, top=15))
    stage("policy", lambda: ctx.invoke(policy, niche=niche))

    report = (
        Path(report)
        if report
        else settings.data_dir / "reports" / f"{time.strftime('%Y-%m-%d')}.md"
    )
    rep.write(report, store)
    console.print(f"report: {report}" + (f"  failed: {rep.failed}" if rep.failed else "  all ok"))
    if rep.failed:
        ctx.exit(1)


@cli.command()
@click.argument("niche")
@click.option(
    "--out", type=click.Path(), default=None, help="index.html path (default data/site/index.html)"
)
@click.option("--no-assets", is_flag=True, help="Do not copy clips next to the page")
def dashboard(niche, out, no_assets):
    """Static HTML dashboard from the db: what works, concepts, clips, scripts, creators, payouts."""
    from .dashboard import render as render_dashboard

    out = Path(out) if out else settings.data_dir / "site" / "index.html"
    console.print(f"dashboard: {render_dashboard(_store(), niche, out, copy_assets=not no_assets)}")


@cli.group()
def sync():
    """Move the SQLite between this machine and the API (MKT_API_URL, MKT_API_TOKEN)."""


def _api():
    import os

    url = os.environ.get("MKT_API_URL", "https://mkt-api.fly.dev").rstrip("/")
    return url, os.environ.get("MKT_API_TOKEN")


@sync.command("pull")
def sync_pull():
    """Download the API's db over the local one (skips when the API has none yet)."""
    import httpx

    url, _ = _api()
    r = httpx.get(f"{url}/db", timeout=120, follow_redirects=True)
    if r.status_code == 404:
        console.print("api has no db yet, keeping local")
        return
    r.raise_for_status()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.db_path.write_bytes(r.content)
    console.print(f"pulled {len(r.content)} bytes -> {settings.db_path}")


@sync.command("push")
def sync_push():
    """Upload the local db to the API (needs MKT_API_TOKEN)."""
    import httpx

    url, token = _api()
    if not token:
        raise click.ClickException("MKT_API_TOKEN not set")
    r = httpx.post(
        f"{url}/db",
        content=settings.db_path.read_bytes(),
        headers={"Authorization": f"Bearer {token}", "content-type": "application/octet-stream"},
        timeout=120,
    )
    r.raise_for_status()
    console.print(f"pushed {r.json()['bytes']} bytes -> {url}")


@cli.group()
def devin():
    """Have Devin run the loop: start a session through the Devin API that runs `mkt daily`,
    fixes what broke, pushes the state branch and reports."""


@devin.command("kickoff")
@click.argument("niche")
@click.argument("tags", nargs=-1, required=True)
@click.option("--product", required=True)
@click.option("--renders", default=1)
@click.option("--resolution", default="480p")
@click.option("--repo", default=None, help="owner/repo (default MKT_REPO)")
@click.option("--max-acu", default=10, help="ACU cap for the session")
@click.option("--wait/--no-wait", default=False, help="Block until the session settles")
@click.option("--dry-run", is_flag=True, help="Print the prompt, start nothing")
def devin_kickoff(niche, tags, product, renders, resolution, repo, max_acu, wait, dry_run):
    from .orchestrator import DEFAULT_REPO, DevinClient, daily_prompt

    repo = repo or DEFAULT_REPO
    prompt = daily_prompt(niche, list(tags), product, renders, resolution, repo)
    if dry_run:
        click.echo(prompt)
        return
    client = DevinClient()
    s = client.create_session(
        prompt,
        title=f"mkt daily {niche} {time.strftime('%Y-%m-%d')}",
        tags=["marketing-agent", niche],
        repos=[repo],
        max_acu_limit=max_acu,
    )
    _store().insert(
        "runs",
        {
            "created_at": int(time.time()),
            "session_id": s["session_id"],
            "url": s["url"],
            "niche": niche,
            "product": product,
            "note": "cli",
        },
    )
    console.print(f"session {s['session_id']}: {s['url']}")
    if wait:
        s = client.wait(s["session_id"])
        console.print(f"{s.get('status')} / {s.get('status_detail')}")
        for pr in s.get("pull_requests") or []:
            console.print(f"PR {pr.get('pr_url')} [{pr.get('pr_state')}]")


@devin.command("status")
@click.argument("session_id")
def devin_status(session_id):
    from .orchestrator import DevinClient

    s = DevinClient().get_session(session_id)
    console.print(f"{s.get('title')}: {s.get('status')} / {s.get('status_detail')}  {s.get('url')}")
    for pr in s.get("pull_requests") or []:
        console.print(f"PR {pr.get('pr_url')} [{pr.get('pr_state')}]")
    if s.get("structured_output"):
        console.print(json.dumps(s["structured_output"], indent=2))


if __name__ == "__main__":
    cli()
