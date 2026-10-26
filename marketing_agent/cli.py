"""`mkt` CLI. Pipeline: scrape -> download -> classify -> concepts -> scripts -> render -> own posts -> scoreboard.
`run` chains the research half."""

import json
import re
import time
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from .config import settings
from .store import Store

console = Console()


def _campaign():
    from . import campaign as campaign_cfg

    return campaign_cfg.load()


def _niche(niche):
    return niche or _campaign().niche.name


def _tags(tags, niche=None):
    tags = list(tags) or _campaign().niche.hashtags or (_store().niche_tags(niche) if niche else [])
    if not tags:
        raise click.UsageError("No hashtags given and campaign.toml has none")
    return tags


def _product(product):
    return product or _campaign().product.description


def _store() -> Store:
    return Store(settings.db_path)


@click.group()
def cli():
    """Marketing agent: research, classify, generate."""


@cli.command()
@click.argument("tags", nargs=-1)
@click.option("--scrolls", default=3)
def scrape(tags, scrolls):
    """Pull fresh videos for hashtags from TikTok (browser via CDP) into the store."""
    tags = _tags(tags)
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
@click.option("--limit", default=None, type=int, help="Videos this run (default: all of them)")
@click.option("--model", default=None)
@click.option(
    "--niche",
    default=None,
    help="Instead of whatever is downloaded, classify the niche's scored research videos that"
    " have no tags yet (newest first), downloading each one first",
)
def classify(limit, model, niche):
    """Tag downloaded, untagged videos with the multimodal classifier. With --niche, work through
    the scored research panel instead, so trait tables rest on the videos that have a score. The
    default is every video that qualifies: a scored video without tags is a lost lesson, and after
    the first full pass only the cycle's new videos are left each run."""
    from .classifier.classify import classify as run_classify
    from .research.tiktok_browser import fetch_video_sync

    store = _store()
    model = model or settings.openai_model
    rows = store.untagged(limit) if niche is None else panel_untagged(store, _niche(niche), limit)
    console.print(f"{len(rows)} to classify")
    done = 0
    for v in rows:
        path = Path(v["local_path"] or "")
        if not v["local_path"] or not path.exists():
            # local_path can come from another machine's db (mkt sync pull), or be unset for a
            # panel video that was only ever observed
            path = settings.videos_dir / f"{v['id']}.mp4"
            try:
                fetch_video_sync(v["url"], path, settings.cdp_url)
            except Exception as e:  # noqa: BLE001 - one unfetchable video must not stop the rest
                console.print(f"[red]{v['id']}: {e!r}")
                continue
            store.set_local_path(v["id"], str(path))
        v["hashtags"] = json.loads(v["hashtags"] or "[]")
        res = run_classify(path, v, model=model, transcribe_model=settings.transcribe_model)
        store.save_tags(v["id"], model, res)
        done += 1
        tg = res["tags"]
        console.print(
            f"{v['id']} {res['run']['latency_s']}s  {tg['hook_type']:>15} | {tg['visual_style']:>18} | "
            f"demo {tg['demo_score_1_5']} | {tg['concept'][:70]}"
        )
    return f"{done} classified"


def panel_untagged(store, niche: str, limit: int | None = None) -> list[dict]:
    """The niche's scored research videos (a day old, so they have a lift) without tags, newest
    first: the ones whose score a classification would turn into a trait lesson. All of them
    unless `limit` says otherwise."""
    from .scoreboard import build

    sb = build(store, tags=store.niche_tags(niche) or None)
    scored = [v for v in sb["videos"] if v.get("reward") is not None and not v.get("hook_type")]
    scored.sort(key=lambda v: -(v.get("create_time") or 0))
    return scored if limit is None else scored[:limit]


@cli.command()
@click.argument("niche", required=False)
@click.argument("tags", nargs=-1)
@click.option("--scrolls", default=6)
@click.option("--max-classify", default=100, help="Cohort videos to download and tag this run")
def cohort(niche, tags, scrolls, max_classify):
    """Enroll fresh videos (<6h old) from the niche's hashtags as a cohort, snapshot their
    creators, download and tag all of them, and build the feature rows. Repoll keeps the curves."""
    niche = _niche(niche)
    tags = _tags(tags, niche)
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
@click.option("--niche", multiple=True, help="Restrict to these niches (default: all in the panel)")
def analyze(niche):
    """Fit the controlled-effect tables (trait x outcome, pooled and per niche) on the cohort
    feature rows and store them as the latest findings."""
    from .analysis import analyze as run_analyze
    from .analysis import save_findings

    store = _store()
    res = run_analyze(store, list(niche) or None)
    save_findings(store, res)
    st = res["status"]
    console.print(
        f"panel {st['videos']} videos, {st['tagged']} tagged, reached 72h: {st['reached']['72h']}"
    )
    from .analysis import DEFAULT_OUTCOME

    for trait, fit in res["fits"][DEFAULT_OUTCOME]["pooled"].items():
        for lvl in fit.get("levels", []):
            if not lvl["reference"]:
                console.print(
                    f"{trait:>24} {lvl['level']:>18} {lvl['coef']:+.2f} "
                    f"[{lvl['lo']:+.2f},{lvl['hi']:+.2f}] n={lvl['n']} {lvl['verdict']}"
                )


@cli.group()
def own():
    """Discover our accounts' posts and feed performance back into the picker. Never posts."""


@own.command("login")
def own_login():
    """Verify/reuse Chrome's TikTok login, or log in using protected environment credentials."""
    from .research.tiktok_auth import LoginRequired, ensure_login_sync

    try:
        status = ensure_login_sync(settings.cdp_url)
    except LoginRequired as exc:
        raise click.ClickException(str(exc)) from None
    console.print(f"TikTok session verified ({status}). Nothing posted.")


@own.command("add")
@click.argument("handle")
@click.option("--tag", default="", help="Optional campaign hashtag for fallback discovery")
@click.option("--product", default="")
def own_add(handle, tag, product):
    from .own import add_account

    add_account(_store(), handle, tag, product)
    console.print("Account registered for profile discovery. Historical posts are baseline only.")


@own.command("post")
@click.argument("url")
@click.option("--caption", default="", help="The caption used, so the post links to its script now")
@click.option("--niche", default=None)
def own_post(url, caption, niche):
    """Register a post a person made from one of our accounts by its TikTok link."""
    from .own import add_post

    try:
        res = add_post(_store(), url, caption, niche=_niche(niche))
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    console.print(res)


@own.command("sync")
@click.argument("niche", required=False)
@click.argument("tags", nargs=-1)
@click.option("--source", type=click.Choice(["profile", "hashtag"]), default="profile")
def own_sync(niche, tags, source="profile"):
    """Read our profiles in Chrome; --source hashtag explicitly opts into fallback discovery."""
    niche = _niche(niche)
    tags = _tags(tags, niche)
    from .own import sync_own
    from .research.tiktok_auth import LoginRequired

    store = _store()
    niche_tags = list(tags) or store.niche_tags(niche)
    try:
        console.print(sync_own(store, settings.cdp_url, niche, niche_tags, source=source))
    except LoginRequired as exc:
        raise click.ClickException(str(exc)) from None


@own.command("research")
@click.option("--limit", default=20, help="Max posts to download and tag this run")
@click.option("--model", default=None)
def own_research(limit, model):
    """Download and classify our accounts' campaign posts so we know which hook, style and pacing each one actually used, not only which script it
    came from."""
    from .classifier.classify import classify as run_classify
    from .research.tiktok_browser import fetch_video_sync

    store = _store()
    model = model or settings.openai_model
    todo = store.rows(
        """SELECT v.* FROM videos v WHERE v.ours=1
            AND NOT EXISTS (SELECT 1 FROM tags t WHERE t.video_id=v.id)
            ORDER BY v.create_time DESC LIMIT ?""",
        (limit,),
    )
    tagged = failed = 0
    for v in todo:
        try:
            if not (v.get("local_path") and Path(v["local_path"]).exists()):
                out = settings.videos_dir / f"{v['id']}.mp4"
                fetch_video_sync(v["url"], out, settings.cdp_url)
                store.set_local_path(v["id"], str(out))
                v["local_path"] = str(out)
            v["hashtags"] = json.loads(v["hashtags"] or "[]")
            res = run_classify(
                Path(v["local_path"]), v, model=model, transcribe_model=settings.transcribe_model
            )
            store.save_tags(v["id"], model, res)
            tagged += 1
            console.print(f"{v['id']} @{v['author']}: {res['tags']['hook_type']}")
        except Exception as e:  # noqa: BLE001 - one bad post must not stop the rest
            failed += 1
            console.print(f"[red]{v['id']}: {e!r}")
    note = f"{tagged}/{len(todo)} of our posts tagged"
    console.print(note)
    if failed:
        raise click.ClickException(f"{note}, {failed} failed")
    return note


@own.command("list")
def own_list():
    from .own import own_posts

    store = _store()
    for p in own_posts(store):
        hook = store.tags_for([p["id"]]).get(p["id"], {}).get("tags", {}).get("hook_type")
        console.print(
            f"{p['id']} @{p['author']} {p['age_h']}h views={p['views_now']} "
            f"script={p['script_id']} concept={p['concept']} hook={hook} lift_now={p['lift_now']}"
        )


@cli.command()
@click.option("--out", default="site/frames", help="Directory for <video_id>.jpg posters")
def frames(out):
    """Poster frame for every downloaded video and rendered clip (served next to the dashboard)."""
    from .cohort import poster_frames

    console.print(f"frames: {poster_frames(_store(), out)} new in {out}")


def _transient(e: BaseException) -> bool:
    """A provider-side failure worth one retry: fal 5xx, downstream_service_error, timeouts."""
    msg = str(e)
    return bool(re.search(r"\b5\d\d\b|downstream_service_error|timed? ?out|temporarily", msg, re.I))


@cli.command("render-latest")
@click.option("--renders", default=None, type=int, help="Clips to make; default campaign.toml")
@click.option("--resolution", default=None, help="480p, 720p or 1080p; default campaign.toml")
@click.option("--ref", "refs", multiple=True, help="Reference images; default campaign.toml")
@click.pass_context
def render_latest(ctx, renders, resolution, refs):
    """Render the best not-yet-rendered scripts of the latest batch (the scripts the last cycle
    wrote, by demo score). The site's Generate clips button runs this in a Devin session. A fal
    moderation rejection skips to the next script; a locked account stops with 'needs a top-up'."""
    from .video.generate import fal_locked

    c = _campaign()
    renders = renders if renders is not None else c.cycle.clips
    resolution = resolution or c.cycle.resolution
    refs = tuple(refs) or tuple(c.product.references)
    store = _store()
    latest = store.rows(
        "SELECT MAX(created_at) AS t FROM scripts WHERE product=?", (c.product.description,)
    )
    if not latest or latest[0]["t"] is None:
        raise click.ClickException("no scripts yet; run a cycle first")
    day_start = latest[0]["t"] - 6 * 3600
    from .policy import rank_scripts

    todo = [
        r["id"]
        for r in rank_scripts(
            store.rows(
                "SELECT s.id, s.demo_score, s.payload FROM scripts s "
                "LEFT JOIN renders r ON r.script_id=s.id "
                "WHERE s.product=? AND s.created_at>=? AND r.id IS NULL",
                (c.product.description, day_start),
            )
        )
    ]
    if not todo:
        raise click.ClickException("every script in the latest batch is already rendered")
    if (lock := fal_locked()) is not None:
        raise click.ClickException(f"needs a top-up at fal.ai/dashboard/billing: {lock}")
    made: list[int] = []
    retried: dict[int, bool] = {}
    for sid in todo:  # a retried script is appended to the end and seen again
        if len(made) >= renders:
            break
        try:
            ctx.invoke(
                render,
                script_ids=(sid,),
                provider=None,
                duration=12,
                resolution=resolution,
                sound=None,
                ref=refs,
            )
            made.append(sid)
        except Exception as e:  # noqa: BLE001 - only moderation is skippable
            if "Exhausted balance" in str(e) or "User is locked" in str(e):
                raise click.ClickException(
                    f"rendered {', '.join(f's{i}' for i in made) or 'nothing'}; fal balance ran "
                    f"out, needs a top-up at fal.ai/dashboard/billing (wanted {renders})"
                ) from e
            if "content_policy_violation" in str(e):
                continue
            if retried.get(sid) or not _transient(e):
                raise
            retried[sid] = True
            console.print(f"[yellow]s{sid}: {e}; retrying once")
            todo.append(sid)
    console.print(f"rendered {len(made)} of {renders}: {' '.join(f's{i}' for i in made)}")


@cli.command()
@click.argument("name")
@click.argument("status", type=click.Choice(["ok", "failed", "skipped"]))
@click.argument("note", required=False, default="")
def stage(name, status, note):
    """Record the outcome of a stage rerun by hand on the newest run of the campaign's niche, so
    the Runs page shows the rerun's result instead of the first attempt's error."""
    from .orchestrator import record_stage

    rid = record_stage(_store(), _campaign().niche.name, name, status, note)
    console.print(f"run {rid}: {name} {status}" if rid else "no recorded run to update")


@cli.command()
@click.option("--max-age-days", default=8.0)
@click.option("--niche", default=None)
def repoll(max_age_days, niche):
    """Re-record public stats for every tracked video (our posts and the cohort) still inside the
    window, then rebuild features. No browser needed; the cycle runs this first, and the site's
    "Check post performance" button runs it on demand."""
    from .cohort import build_features
    from .cohort import repoll as do_repoll

    store = _store()
    res = do_repoll(store, max_age_days, niche)
    res["features"] = build_features(store, niche)
    console.print(res)


@cli.command()
@click.argument("niche", required=False)
@click.option("--tag", default=None)
@click.option("--max-age-h", default=72)
@click.option("--limit", default=40)
def concepts(niche, tag, max_age_h, limit):
    """Cluster ranked videos into reusable concepts and store them."""
    niche = _niche(niche)
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
    """Generate a clip per script with Seedance and cut two 1080x1920 videos: the captioned preview
    (s<id>.mp4) and a clean copy with no text (s<id>_clean.mp4) that is the one to post, with the
    hook typed into TikTok's own text tool so TikTok reads it as text, not pixels."""
    from . import campaign as campaign_cfg
    from .learnings import rules as review_rules
    from .video.edit import assemble, captions_from_script, probe_duration
    from .video.generate import GenRequest, get_provider

    store = _store()
    prov = get_provider(provider)
    rules = review_rules(store, campaign_cfg.load().niche.name)
    for sid in script_ids:
        rows = store.rows("SELECT * FROM scripts WHERE id=?", (sid,))
        if not rows:
            console.print(f"[red]no script {sid}")
            continue
        s = json.loads(rows[0]["payload"])
        raw = settings.renders_dir / f"s{sid}_raw.mp4"
        final = settings.renders_dir / f"s{sid}.mp4"
        clean = settings.renders_dir / f"s{sid}_clean.mp4"
        t0 = time.time()
        res = prov.generate(
            GenRequest(
                prompt=s["video_prompt"],
                duration_s=duration,
                resolution=resolution,
                reference_images=list(ref),
                rules=rules,
            ),
            raw,
        )
        caps = captions_from_script(s["hook"], s.get("captions") or [], probe_duration(raw))
        assemble([raw], final, captions=caps, sound=Path(sound) if sound else None)
        assemble([raw], clean, sound=Path(sound) if sound else None)
        store.insert(
            "renders",
            {
                "script_id": sid,
                "created_at": int(time.time()),
                "model": res.model,
                "prompt": s["video_prompt"],
                "raw_path": str(raw),
                "final_path": str(final),
                "post_path": str(clean),
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
@click.option(
    "--group",
    type=click.Choice(["reference", "ours", "both"]),
    default="both",
    help="reference = videos scraped for research, ours = our registered accounts",
)
def scoreboard(tag, top, group):
    """Reward per video (log views vs the account's baseline), hooks and concepts ranked by it,
    and accounts stuck under 1k views. Reference videos and our posts are scored separately."""
    for g in ("ours", "reference") if group == "both" else (group,):
        _scoreboard_group(tag, top, g)


def _scoreboard_group(tag, top, group):
    from .scoreboard import build, growth

    store = _store()
    sb = build(store, tag, group=group)
    title = "Our posts" if group == "ours" else "Reference videos (research)"
    console.print(
        f"[bold]{title}[/bold]: {len(sb['videos'])} videos, {sb['n_scored']} old enough to score, "
        f"{sb['n_tagged']} tagged"
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


@cli.command("compare")
@click.option("--tag", default=None)
@click.option("--top", default=20)
def compare_cmd(tag, top):
    """Our posts next to the market: each hook, style and concept with its lift on reference
    videos and on our posts, disagreements first."""
    from .compare import compare

    rows = compare(_store(), tag)
    if not rows:
        console.print("[dim]nothing scored on either side yet")
        return
    t = Table("trait", "value", "market", "n", "ours", "n", "read")
    for r in rows[:top]:
        t.add_row(
            r["trait"],
            str(r["value"])[:40],
            "" if r["market"] is None else f"{r['market']:+.2f}",
            str(r["market_n"]),
            "" if r["ours"] is None else f"{r['ours']:+.2f}",
            str(r["ours_n"]),
            r["verdict"],
        )
    console.print(t)


@cli.command()
@click.argument("niche", required=False)
def policy(niche):
    """What the loop has learned: winning traits and the per-concept prior/observed/sampled scores."""
    niche = _niche(niche)
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
@click.argument("niche", required=False)
@click.argument("tags", nargs=-1)
@click.option("--product", default=None, help="Default: campaign.toml [product].description")
@click.option(
    "--product-tag",
    "product_tags",
    multiple=True,
    help="Hashtags/keywords that identify the product's own TikToks; their top videos become the"
    " format to clone (any age), ahead of the fresh niche concepts",
)
@click.option("--top", default=8)
@click.option("--batch-formats", default=3, help="Formats the script batch spans, by pick share")
@click.option("--batch-per-format", default=2, help="Scripts kept per format")
@click.pass_context
def run(ctx, niche, tags, product, product_tags, top, batch_formats=3, batch_per_format=2):
    """Daily loop: scrape -> download top -> classify -> concepts -> format of the product's own
    best videos -> the picker's top formats -> a batch of scripts across them, each stored with
    why its format was proposed."""
    niche = _niche(niche)
    tags = _tags(tags, niche)
    product = _product(product)
    product_tags = list(product_tags) or _campaign().product.hashtags
    _store().set_niche_tags(niche, list(tags))
    ctx.invoke(scrape, tags=tags, scrolls=3)
    ctx.invoke(download, tag=None, top=top, max_age_h=72)
    ctx.invoke(classify, limit=top, model=None)
    ctx.invoke(concepts, niche=niche, tag=None, max_age_h=72, limit=40)
    if product_tags:
        ctx.invoke(format_cmd, niche=niche, product_tags=product_tags, limit=5)
    if product:
        from .policy import propose_batch, winning_traits
        from .video.scripts import write_scripts

        store = _store()
        for c in propose_batch(store, niche, formats=batch_formats):
            console.print(
                f"format {c['id']} '{c['name']}': picked {c['pick_share']:.0%} of the time, "
                f"head start {c['prior']}, expected lift {c['learned']}, "
                f"our posts n={c['n']} mean {c['mean_reward']}"
            )
            full = store.rows("SELECT payload FROM concepts WHERE id=?", (c["id"],))
            concept = {**json.loads(full[0]["payload"]), "id": c["id"], "name": c["name"]}
            out = write_scripts(
                store,
                concept,
                product,
                n=2 * batch_per_format,
                min_score=3,
                model=settings.openai_model,
                context=winning_traits(store),
                keep=batch_per_format,
                why=c["why"],
            )
            for s in out:
                console.print(f"  #{s['id']} demo {s['demo_score_1_5']}  {s['hook']}")


@cli.command("format")
@click.argument("niche", required=False)
@click.option("--product-tag", "product_tags", multiple=True, required=True)
@click.option("--limit", default=5, help="How many source videos to watch")
def format_cmd(niche, product_tags, limit):
    """Watch the product's best TikToks in the db (frames + transcript) and store their beat sheet
    as a 'format' concept: hook shot, shot order and timings, pacing, text budget, sound."""
    niche = _niche(niche)
    from .research.format import build_format, product_sources

    store = _store()
    srcs = product_sources(store, list(product_tags), limit=limit)
    if not srcs:
        console.print("[yellow]no product videos in the db yet; niche concepts are the fallback")
        return
    t = Table("id", "author", "followers", "views", "dur", "sound", "caption")
    for s in srcs:
        t.add_row(
            s["id"],
            s["author"],
            str(s.get("followers")),
            str(s.get("views")),
            f"{s.get('duration')}s",
            (s.get("music") or "")[:30],
            (s.get("desc") or "")[:50],
        )
    console.print(t)
    out = build_format(
        store, niche, list(product_tags), settings.cdp_url, settings.openai_model, limit
    )
    sheet = out["beat_sheet"]
    console.print(
        f"format concept {out['id']} '{out['name']}': hook {sheet['hook_delivery']} | "
        f"{sheet['on_screen_text_lines']} text line(s) <= {sheet['text_budget_words']} words | "
        f"pacing {sheet['pacing']} | sound {out['sound'] or 'original'}"
    )
    for b in sheet["beats"]:
        console.print(f"  {b['start_s']:.0f}-{b['end_s']:.0f}s {b['shot']}")


@cli.command()
@click.argument("niche", required=False)
@click.argument("tags", nargs=-1)
@click.option("--product", default=None, help="Default: campaign.toml [product].description")
@click.option(
    "--product-tag",
    "product_tags",
    multiple=True,
    help="Hashtags/keywords of the product's own TikToks; the format to clone comes from them",
)
@click.option("--top", default=8)
@click.option(
    "--classify-panel",
    default=None,
    type=int,
    help="Cap on scored research videos without tags to download and classify this run"
    " (default: all of them)",
)
@click.option("--renders", default=None, type=int, help="Clips to render (default campaign.toml)")
@click.option("--resolution", default=None, help="480p, 720p or 1080p (default campaign.toml)")
@click.option(
    "--ref", "refs", multiple=True, help="Reference image URL/path (product shots) for renders"
)
@click.option("--report", type=click.Path(), default=None, help="Markdown report path")
@click.option(
    "--dashboard", "dashboard_out", type=click.Path(), default=None, help="index.html path"
)
@click.pass_context
def daily(
    ctx,
    niche,
    tags,
    product,
    product_tags,
    top,
    classify_panel,
    renders,
    resolution,
    refs,
    report,
    dashboard_out,
):
    """One cycle, every stage in order with a report at the end: our account, measure (re-poll
    our posts and the cohort so the picker learns from fresh numbers), own sync, run (scrape,
    classify, concepts, pick, scripts), cohort, analyze, render, our posts, scoreboard, compare
    (ours vs market), policy. Anything not given comes from campaign.toml. A failed stage is
    recorded and the rest still runs."""
    import os

    from . import campaign as campaign_cfg
    from .orchestrator import DailyReport

    c = campaign_cfg.load()
    niche = niche or c.niche.name
    tags = tuple(tags) or tuple(c.niche.hashtags)
    product = product or c.product.description
    product_tags = tuple(product_tags) or tuple(c.product.hashtags)
    refs = tuple(refs) or tuple(c.product.references)
    renders = c.cycle.clips if renders is None else renders
    resolution = resolution or c.cycle.resolution
    rep = DailyReport(niche, product)

    def _fal_locked():
        from .video.generate import fal_locked

        return fal_locked()

    class Skipped(Exception):
        """A stage that cannot run on this machine for a reason that is not a bug."""

    def stage(name, fn):
        t0 = time.time()
        try:
            note = fn()
            rep.ok(name, time.time() - t0, note or "")
        except Skipped as e:
            rep.skip(name, str(e))
            console.print(f"[yellow]{name} skipped: {e}")
        except Exception as e:  # noqa: BLE001 - every stage must be reported, not raised
            rep.fail(name, e)
            console.print(f"[red]{name} failed: {e!r}")

    def own_stage():
        """Profile sync needs a TikTok login in this machine's Chrome. Without one it is skipped,
        not failed: posts a person makes are registered through the site's Our posts form and
        re-polled by the measure stage, so the cycle is still complete."""
        try:
            return ctx.invoke(own_sync, niche=niche, tags=tags)
        except click.ClickException as e:
            raise Skipped(
                f"no TikTok login on this machine ({e.message}); posts are registered through "
                "the site's Our posts form instead"
            ) from e

    if c.account.handle:
        from .own import add_account

        stage(
            "account",
            lambda: add_account(_store(), c.account.handle, c.account.backup_hashtag, product),
        )
    stage("measure", lambda: ctx.invoke(repoll, max_age_days=8.0, niche=None))
    stage("own", own_stage)
    stage(
        "run",
        lambda: ctx.invoke(
            run, niche=niche, tags=tags, product=product, product_tags=product_tags, top=top
        ),
    )
    stage(
        "cohort",
        lambda: ctx.invoke(cohort, niche=niche, tags=tags, scrolls=6, max_classify=100),
    )
    stage(
        "classify_panel",
        lambda: ctx.invoke(classify, limit=classify_panel, model=None, niche=niche),
    )
    stage("analyze", lambda: ctx.invoke(analyze, niche=()))
    store = _store()
    from .policy import rank_scripts

    todays = [
        r["id"]
        for r in rank_scripts(
            store.rows(
                "SELECT id, demo_score, payload FROM scripts WHERE product=? AND created_at>=?",
                (product, int(rep.started)),
            )
        )
    ]
    if not renders:
        rep.skip("render", "--renders 0")
    elif not todays:
        rep.skip("render", "no scripts written this run")
    elif not os.environ.get("FAL_KEY"):
        rep.skip("render", "FAL_KEY not set")
    elif (lock := _fal_locked()) is not None:
        rep.fail("render", RuntimeError(f"needs a top-up at fal.ai/dashboard/billing: {lock}"))
    else:

        def render_best():
            """Render the N best scripts; a script fal's moderation rejects is skipped (not
            billed) and the next-ranked one takes its place, so the day still yields N clips."""
            made, rejected = [], []
            for sid in todays:
                if len(made) >= renders:
                    break
                try:
                    ctx.invoke(
                        render,
                        script_ids=(sid,),
                        provider=None,
                        duration=12,
                        resolution=resolution,
                        sound=None,
                        ref=tuple(refs),
                    )
                    made.append(sid)
                except Exception as e:  # noqa: BLE001 - only moderation is skippable
                    if "Exhausted balance" in str(e) or "User is locked" in str(e):
                        raise RuntimeError(
                            f"rendered {', '.join(f's{i}' for i in made) or 'nothing'}; "
                            f"fal balance ran out, needs a top-up at fal.ai/dashboard/billing "
                            f"(wanted {renders})"
                        ) from e
                    if "content_policy_violation" not in str(e):
                        raise
                    rejected.append(sid)
                    console.print(f"[yellow]s{sid} rejected by fal moderation, trying next")
            note = f"rendered {', '.join(f's{i}' for i in made) or 'nothing'}"
            if rejected:
                note += f"; moderation rejected {', '.join(f's{i}' for i in rejected)}"
            if len(made) < renders:
                raise RuntimeError(f"{note}; wanted {renders}")
            return note

        stage("render", render_best)
    if dashboard_out:  # after render, so new clips get posters too
        stage(
            "frames",
            lambda: ctx.invoke(frames, out=str(Path(dashboard_out).parent / "frames")),
        )

    stage("own_research", lambda: ctx.invoke(own_research, limit=20, model=None))
    stage("scoreboard", lambda: ctx.invoke(scoreboard, tag=None, top=15, group="both"))
    stage("compare", lambda: ctx.invoke(compare_cmd, tag=None, top=20))
    stage("policy", lambda: ctx.invoke(policy, niche=niche))
    stage("learn", lambda: _learn_cycle(niche, product, rep.stages))

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
@click.argument("niche", required=False)
@click.option(
    "--out", type=click.Path(), default=None, help="index.html path (default data/site/index.html)"
)
@click.option("--no-assets", is_flag=True, help="Do not copy clips next to the page")
def dashboard(niche, out, no_assets):
    """Static HTML dashboard from the db: what works, concepts, clips, scripts, our posts."""
    niche = _niche(niche)
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
@click.argument("niche", required=False)
@click.argument("tags", nargs=-1)
@click.option("--product", default=None, help="Default: campaign.toml")
@click.option("--renders", default=None, type=int)
@click.option("--resolution", default=None)
@click.option("--repo", default=None, help="owner/repo (default MKT_REPO)")
@click.option("--max-acu", default=None, type=int, help="ACU cap for the session")
@click.option("--wait/--no-wait", default=False, help="Block until the session settles")
@click.option("--dry-run", is_flag=True, help="Print the prompt, start nothing")
def devin_kickoff(niche, tags, product, renders, resolution, repo, max_acu, wait, dry_run):
    """Start one cycle as a Devin session (what the site's Run cycle button does). Everything not
    given comes from campaign.toml."""
    from . import campaign as campaign_cfg
    from .orchestrator import DEFAULT_REPO, DevinClient, daily_prompt

    c = campaign_cfg.load()
    niche = niche or c.niche.name
    tags = list(tags) or c.niche.hashtags
    product = product or c.product.description
    renders = c.cycle.clips if renders is None else renders
    resolution = resolution or c.cycle.resolution
    max_acu = c.cycle.max_acu if max_acu is None else max_acu
    repo = repo or DEFAULT_REPO
    prompt = daily_prompt(
        niche,
        tags,
        product,
        renders,
        resolution,
        repo,
        refs=c.product.references,
        product_tags=c.product.hashtags,
    )
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


def _learn_cycle(niche, product, stages):
    from .learnings import write_cycle

    lid = write_cycle(_store(), niche, product, stages)
    return f"learnings entry {lid}"


@cli.group()
def learn():
    """What the agent has learned, in plain words (Learnings page on the site)."""


@learn.command("write")
@click.argument("niche", required=False)
@click.option("--product", default=None)
def learn_write(niche, product):
    """Write this cycle's entry from what is in the db (what the sources showed, what the picker
    leaned on, how our posts did, what changed). `mkt daily` does this as its last stage."""
    from . import campaign as campaign_cfg

    c = campaign_cfg.load()
    console.print(_learn_cycle(niche or c.niche.name, product or c.product.description, None))


@learn.command("add")
@click.argument("title")
@click.option("--body", default=None, help="Markdown; omitted = read stdin")
@click.argument("niche", required=False)
def learn_add(title, body, niche):
    """Add an observation in your own words (the session running a cycle does this: what it saw
    in the videos, what was wrong, what it changed)."""
    import sys

    from . import campaign as campaign_cfg
    from .learnings import add

    c = campaign_cfg.load()
    body = body if body is not None else sys.stdin.read()
    lid = add(_store(), niche or c.niche.name, c.product.description, title, body)
    console.print(f"learnings entry {lid}")


@learn.command("rule")
@click.argument("text")
@click.argument("niche", required=False)
def learn_rule(text, niche):
    """A standing rule in plain words, e.g. "The TV shows our flappy-bird game for the whole
    clip, never another game". From now on every script prompt and every video prompt carries it,
    and it shows on the Learnings page."""
    from . import campaign as campaign_cfg
    from .learnings import add_rule

    c = campaign_cfg.load()
    lid = add_rule(_store(), niche or c.niche.name, c.product.description, text)
    console.print(f"rule {lid}")


@learn.command("hold")
@click.argument("script_id", type=int)
@click.argument("reason")
def learn_hold(script_id, reason):
    """Keep a clip off the ready-to-post list and out of the walkthrough, with the reason shown on
    Clips (e.g. "TV switches to a game that is not ours at 4s")."""
    from .learnings import hold

    n = hold(_store(), script_id, reason)
    console.print(
        f"s{script_id}: {n} render(s) on hold" if n else f"[red]no render for s{script_id}"
    )


@learn.command("release")
@click.argument("script_id", type=int)
def learn_release(script_id):
    """Take a clip off hold."""
    from .learnings import release

    n = release(_store(), script_id)
    console.print(
        f"s{script_id}: released {n} render(s)" if n else f"[red]no render for s{script_id}"
    )


@learn.command("show")
@click.argument("niche", required=False)
def learn_show(niche):
    """Print learnings.md."""
    from .learnings import document

    click.echo(document(_store(), niche))


@cli.command("campaign")
def campaign_show():
    """Print what the loop is for (campaign.toml plus any MKT_* overrides)."""
    from . import campaign as campaign_cfg

    c = campaign_cfg.load()
    console.print(f"[dim]{c.path or 'no campaign.toml, built-in defaults'}")
    console.print(f"account   @{c.account.handle or '(none registered)'}")
    console.print(f"niche     {c.niche.name}: {' '.join('#' + t for t in c.niche.hashtags)}")
    console.print(f"product   {c.product.name or c.product.description}")
    console.print(
        f"          clones {' '.join('#' + t for t in c.product.hashtags) or '(no product TikToks)'}"
    )
    console.print(f"          {len(c.product.references)} reference images")
    console.print(
        f"cycle     {c.cycle.clips} clips at {c.cycle.resolution}, {c.cycle.max_acu} ACU cap"
    )


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
