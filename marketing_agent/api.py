"""HTTP backend over the same SQLite the CLI uses. Reads are open; writes need
`Authorization: Bearer $MKT_API_TOKEN`. Run: uvicorn marketing_agent.api:app --port 8080."""

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from . import campaign as campaign_cfg
from . import policy, scoreboard
from .analysis import analyze, latest_findings, save_findings
from .cohort import build_features, features, latest_snapshot, repoll
from .config import settings
from .labels import copy_to_tags, labels_of
from .learnings import document as learnings_doc
from .learnings import entries as learnings_entries
from .learnings import hold as learnings_hold
from .learnings import migrate as learnings_migrate
from .learnings import release as learnings_release
from .own import accounts as own_accounts
from .own import own_posts, own_rewards
from .policy import concept_scores, winning_traits
from .scoreboard import build
from .store import Store
from .video.edit import strip_label

CAMPAIGN = campaign_cfg.load()
DEFAULT_NICHE = CAMPAIGN.niche.name


def _store() -> Store:
    return Store(settings.db_path)


def _auth(authorization: str | None = Header(default=None)) -> None:
    token = os.environ.get("MKT_API_TOKEN")
    if not token:
        raise HTTPException(503, "MKT_API_TOKEN not configured; writes disabled")
    if authorization != f"Bearer {token}":
        raise HTTPException(401, "bad token")


log = logging.getLogger("mkt.api")


async def _post_retry_loop() -> None:
    while True:
        await asyncio.sleep(POST_RETRY_EVERY_S)
        try:
            again = await asyncio.to_thread(retry_stale_posts, _store())
            if again:
                log.info("handed back to the poster session: %s", again)
        except Exception:  # noqa: BLE001
            log.exception("post retry failed")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """The retry of stale clip hand-offs lives in the API, not in anyone's reminders. Off when
    the API cannot reach Devin anyway, or with MKT_POST_RETRY=0."""
    task = None
    if os.environ.get("MKT_POST_RETRY", "1") != "0" and os.environ.get("DEVIN_API_KEY"):
        task = asyncio.create_task(_post_retry_loop())
    yield
    if task:
        task.cancel()


app = FastAPI(title="marketing-agent", version="0.1", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("MKT_CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": True, "db": str(settings.db_path)}


@app.get("/overview")
def overview(niche: str = DEFAULT_NICHE):
    store = _store()
    sb = build(store, tags=store.niche_tags(niche) or None)
    spent = sum(r["cost_usd"] or 0 for r in store.rows("SELECT cost_usd FROM renders"))
    return {
        "niche": niche,
        "videos": len(sb["videos"]),
        "scored": sb["n_scored"],
        "tagged": sb["n_tagged"],
        "trait_min_n": sb["trait_min_n"],
        "concepts": len(concept_scores(store, niche)),
        "spent_usd": round(spent, 2),
        "winning": winning_traits(store),
        "hooks": sb["hooks"][:8],
        "styles": sb["styles"][:8],
        "pacing": sb["pacing"][:8],
        "sound": sb["sound"][:8],
        "product_early": sb["product_early"][:8],
        "concept_rank": sb["concepts"][:8],
        "stuck_accounts": build(store, group="ours")["stuck_accounts"],
        "top_videos": [v for v in sb["videos"] if v.get("hook_type")][:20],
    }


@app.get("/logic")
def logic(niche: str = DEFAULT_NICHE):
    """What the "How it decides" page draws: every research video's views against its creator's
    usual (both log10, as scored) and the picker's constants, so the page never hardcodes them."""
    store = _store()
    sb = build(store, tags=store.niche_tags(niche) or None)
    clone = next((c for c in policy.concept_scores(store, niche) if c["kind"] == "format"), None)
    keys = (
        "id",
        "author",
        "views",
        "followers",
        "create_time",
        "observed_at",
        "log_views",
        "expected",
        "creator_offset",
        "baseline",
        "reward",
    )
    return {
        "niche": niche,
        "videos": [{k: v.get(k) for k in keys} for v in sb["videos"]],
        "explore_sd": policy.EXPLORE_SD,
        "format_edge": policy.FORMAT_EDGE,
        "shrink_k": policy.SHRINK_K,
        "market_trait_weight": policy.MARKET_TRAIT_WEIGHT,
        "format_prior": clone["prior"] if clone else None,
        "min_age_h": scoreboard.MIN_AGE_H_FOR_JUDGEMENT,
        "min_age_h_own": scoreboard.MIN_AGE_H_FOR_OWN,
        "winsor_pct": scoreboard.WINSOR_PCT,
        "engagement_weight": scoreboard.ENGAGEMENT_WEIGHT,
        "curve": sb["curve"],
    }


@app.get("/concepts")
def concepts(niche: str = DEFAULT_NICHE):
    """Formats with how often the picker would choose each (pick_share) and, on every example
    video, its lift against videos of the same age and account size."""
    from .policy import pick_shares
    from .scoreboard import build

    store = _store()
    rows = concept_scores(store, niche)
    sb = build(store, tags=store.niche_tags(niche) or None)
    lift = {v["id"]: v.get("reward") for v in sb["videos"]}
    for c, share in zip(rows, pick_shares(rows), strict=False):
        c["pick_share"] = round(share, 3)
        for e in c.get("examples", []):
            e["reward"] = lift.get(e["id"])
    return rows


@app.get("/scripts")
def scripts(
    days: int = 7, product: str | None = None, limit: int = 100, niche: str = DEFAULT_NICHE
):
    since = int(time.time()) - days * 86400
    sql = """SELECT s.id, s.concept_id, c.name concept, s.product, s.created_at, s.hook,
                    s.demo_score, s.payload FROM scripts s LEFT JOIN concepts c ON c.id=s.concept_id
             WHERE s.created_at>=? AND c.niche=?"""
    args: list = [since, niche]
    if product:
        sql += " AND s.product=?"
        args.append(product)
    sql += " ORDER BY s.created_at DESC, s.demo_score DESC LIMIT ?"
    args.append(limit)
    out = []
    for r in _store().rows(sql, tuple(args)):
        payload = json.loads(r.pop("payload") or "{}")
        r["hook"] = strip_label(r["hook"] or "")
        sound_id = payload.get("sound_id") or ""
        out.append(
            {
                **r,
                "captions": payload.get("captions"),
                "body": payload.get("body"),
                "spoken": payload.get("spoken", ""),
                "hook_on_screen": payload.get("hook_on_screen", True),
                "sound": payload.get("sound", ""),
                "sound_url": _sound_url(payload.get("sound", ""), sound_id),
                "why": payload.get("why"),
            }
        )
    return out


class HoldIn(BaseModel):
    reason: str = ""


@app.post("/renders/{script_id}/hold", dependencies=[Depends(_auth)])
def hold_render(script_id: int, body: HoldIn):
    """Keep a clip off the ready-to-post list and out of the walkthrough; the reason shows on
    Clips. The Clips page's Hold button and `mkt learn hold` call this."""
    n = learnings_hold(_store(), script_id, body.reason)
    if not n:
        raise HTTPException(404, f"no render for s{script_id}")
    return {"script_id": script_id, "hold_reason": body.reason or "on hold"}


@app.post("/renders/{script_id}/release", dependencies=[Depends(_auth)])
def release_render(script_id: int):
    n = learnings_release(_store(), script_id)
    if not n:
        raise HTTPException(404, f"no render for s{script_id}")
    return {"script_id": script_id, "hold_reason": None}


@app.get("/renders")
def renders(limit: int = 50, niche: str = DEFAULT_NICHE):
    """Real clips only: the stub provider's colour cards are for offline tests, not the site.
    `post_text` is the on-screen text as lines, for the poster to type into TikTok's text tool
    over the clean clip (`post_path`); older renders without a clean copy have post_path null.
    `hold_reason` is set when a reviewer held the clip back (see /renders/{script_id}/hold)."""
    store = _store()
    learnings_migrate(store)
    rows = store.rows(
        """SELECT r.id, r.script_id, r.created_at, r.model, r.cost_usd, r.final_path, r.post_path,
                  r.post_session_url, r.post_requested_at, COALESCE(r.post_attempts, 0) post_attempts,
                  r.hold_reason, s.hook, s.payload, r.payload rpayload
           FROM renders r JOIN scripts s ON s.id=r.script_id JOIN concepts c ON c.id=s.concept_id
           WHERE r.final_path IS NOT NULL AND r.model!='stub' AND c.niche=?
           ORDER BY r.created_at DESC LIMIT ?""",
        (niche, limit),
    )
    for r in rows:
        payload = json.loads(r.pop("payload") or "{}")
        # Scripts often list the hook again as caption fragments ("POV: cardio" + "finally got
        # fun"); the poster types the hook once, so those fragments are not repeated.
        r["post_text"] = _post_text(r["hook"], payload)
        r["hook"] = strip_label(r["hook"] or "")
        lab = labels_of(json.loads(r.pop("rpayload") or "{}"))
        r["labels"] = (
            {
                "tags": lab["tags"],
                "beats": lab["tags"].get("beats") or [],
                "model": (lab.get("run") or {}).get("model"),
            }
            if lab
            else None
        )
    return rows


CLIPS_URL = os.environ.get("MKT_CLIPS_URL", "https://mkt-dashboard-eta.vercel.app/renders")
API_PUBLIC_URL = os.environ.get("MKT_API_URL", "https://mkt-api.fly.dev")
# A clip handed to the poster session that has no registered post after this long can be handed
# over again (the login failed, the session died); the poster is told never to post a clip twice.
POST_RETRY_AFTER_S = 3600
MAX_POST_ATTEMPTS = 4  # automatic hand-backs per clip; a person pressing Post is never capped
POST_RETRY_EVERY_S = 1800


def _sound_url(name: str, sound_id: str) -> str:
    """The sound's TikTok page when the research kept its id, else a TikTok search for its title
    (older scripts carry only the name), so the poster can always click through to find it."""
    if sound_id:
        return f"https://www.tiktok.com/music/x-{sound_id}"
    return f"https://www.tiktok.com/search?q={quote_plus(name)}" if name else ""


def _post_text(hook: str, payload: dict) -> list[str]:
    hook = strip_label(hook or "") if payload.get("hook_on_screen", True) else ""
    caps = [ln.strip() for ln in payload.get("captions") or [] if ln.strip()]
    caps = [ln for ln in caps if not (hook and ln.lower() in hook.lower())]
    return ([hook] if hook else []) + caps


@app.post("/renders/{script_id}/post", dependencies=[Depends(_auth)])
def post_render(script_id: int):
    """The Post button, and step 5 of a render cycle: hand this script's clean clip to the
    account's poster session (one long-lived Devin session that stays signed in to TikTok), which
    uploads it through TikTok's web uploader, adds the text with TikTok's text tool, picks the
    sound and registers the post. One clip per call, never twice for the same clip."""
    return _hand_off(_store(), script_id, by_hand=True)


@app.post("/renders/retry", dependencies=[Depends(_auth)])
def retry_posts():
    """What the API does on its own every POST_RETRY_EVERY_S; here for the cycle and for tests."""
    return {"retried": retry_stale_posts(_store())}


def retry_stale_posts(store: Store) -> list[int]:
    """Clips handed to the poster session more than POST_RETRY_AFTER_S ago with no registered
    post go back to it (a TikTok lockout or a dead session only delays the post), at most
    MAX_POST_ATTEMPTS times each. Returns the script ids handed back."""
    store.migrate()
    rows = store.rows(
        """SELECT DISTINCT r.script_id FROM renders r
           WHERE r.post_session_url IS NOT NULL AND r.post_requested_at < ?
             AND COALESCE(r.post_attempts, 0) < ? AND r.hold_reason IS NULL
             AND r.final_path IS NOT NULL AND r.post_path IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM videos v WHERE v.script_id=r.script_id AND v.ours=1)
           ORDER BY r.script_id""",
        (int(time.time()) - POST_RETRY_AFTER_S, MAX_POST_ATTEMPTS),
    )
    again = []
    for row in rows:
        try:
            res = _hand_off(store, row["script_id"], by_hand=False)
        except (HTTPException, RuntimeError) as e:
            log.warning("s%s not handed back: %s", row["script_id"], e)
            continue
        if not res.get("already"):
            again.append(row["script_id"])
    return again


def _hand_off(store: Store, script_id: int, by_hand: bool) -> dict:
    from .orchestrator import DEFAULT_REPO, DevinClient, post_prompt, poster_session

    store.migrate()
    learnings_migrate(store)
    rows = store.rows(
        """SELECT r.id, r.post_path, r.post_session_url, r.post_requested_at, r.hold_reason,
                  COALESCE(r.post_attempts, 0) post_attempts, s.hook, s.payload
           FROM renders r JOIN scripts s ON s.id=r.script_id
           WHERE r.script_id=? AND r.final_path IS NOT NULL ORDER BY r.created_at DESC LIMIT 1""",
        (script_id,),
    )
    if not rows:
        raise HTTPException(404, "no clip for that script")
    r = rows[0]
    if not r["post_path"]:
        raise HTTPException(400, "this clip has no clean copy to post; render it again")
    if r["hold_reason"]:
        raise HTTPException(400, f"clip is on hold: {r['hold_reason']}")
    now = int(time.time())
    if r["post_session_url"]:
        posted = store.rows(
            "SELECT 1 FROM videos WHERE script_id=? AND ours=1 LIMIT 1", (script_id,)
        )
        fresh = (r["post_requested_at"] or 0) > now - POST_RETRY_AFTER_S
        capped = not by_hand and r["post_attempts"] >= MAX_POST_ATTEMPTS
        if posted or fresh or capped:
            return {"ok": True, "url": r["post_session_url"], "already": True}
    payload = json.loads(r["payload"] or "{}")
    text = _post_text(r["hook"], payload)
    tags = " ".join(
        f"#{t.lstrip('#')}" for t in (CAMPAIGN.product.hashtags + CAMPAIGN.niche.hashtags)[:4]
    )
    caption = " ".join(x for x in (strip_label(r["hook"] or ""), tags) if x)
    s, reused = poster_session(
        store,
        DevinClient(),
        CAMPAIGN.account.handle,
        post_prompt(
            script_id,
            f"{CLIPS_URL}/s{script_id}_clean.mp4",
            text,
            caption,
            payload.get("sound") or "",
            _sound_url(payload.get("sound") or "", payload.get("sound_id") or ""),
            CAMPAIGN.account.handle,
            API_PUBLIC_URL,
        ),
        tags=["marketing-agent", "post", "api"],
        repos=[DEFAULT_REPO],
        max_acu_limit=CAMPAIGN.cycle.max_acu,
    )
    with store.conn() as c:
        c.execute(
            """UPDATE renders SET post_session_url=?, post_requested_at=?,
                                  post_attempts=COALESCE(post_attempts, 0) + 1 WHERE id=?""",
            (s["url"], now, r["id"]),
        )
    store.insert(
        "runs",
        {
            "created_at": now,
            "session_id": s["session_id"],
            "url": s["url"],
            "niche": DEFAULT_NICHE,
            "product": CAMPAIGN.product.description,
            "note": f"post s{script_id} from @{CAMPAIGN.account.handle}"
            + ("" if r["post_attempts"] == 0 else f" (try {r['post_attempts'] + 1})"),
        },
    )
    return {
        "ok": True,
        "url": s["url"],
        "session_id": s["session_id"],
        "reused": reused,
        "attempt": r["post_attempts"] + 1,
    }


@app.get("/renders/{render_id}/file")
def render_file(render_id: int):
    rows = _store().rows("SELECT final_path FROM renders WHERE id=?", (render_id,))
    if not rows or not rows[0]["final_path"] or not Path(rows[0]["final_path"]).exists():
        raise HTTPException(404, "no file")
    return FileResponse(rows[0]["final_path"], media_type="video/mp4")


@app.get("/runs")
def runs(limit: int = 30):
    return _store().rows("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))


@app.get("/learnings")
def learnings(niche: str | None = None, limit: int = 50):
    """What the agent has learned, newest first: one entry per cycle plus the notes the session
    running it added. Written by `mkt learn`."""
    return learnings_entries(_store(), niche, limit)


@app.get("/learnings.md", response_class=PlainTextResponse)
def learnings_md(niche: str | None = None):
    """The same as one markdown file."""
    return learnings_doc(_store(), niche)


@app.get("/campaign")
def campaign():
    """What the loop is for: the account we post from, the niche watched, the product and
    how many clips a cycle makes. Comes from campaign.toml in the repo."""
    return CAMPAIGN.model_dump()


class RunIn(BaseModel):
    """One cycle of the loop. Every field defaults to campaign.toml, so the site's Run cycle
    button posts an empty body."""

    niche: str = CAMPAIGN.niche.name
    tags: list[str] = CAMPAIGN.niche.hashtags
    product: str = CAMPAIGN.product.description
    product_tags: list[str] = CAMPAIGN.product.hashtags
    refs: list[str] = CAMPAIGN.product.references
    renders: int = CAMPAIGN.cycle.clips
    resolution: str = CAMPAIGN.cycle.resolution
    max_acu: int = CAMPAIGN.cycle.max_acu
    mode: str = "full"  # full | research (no renders, no fal spend) | render (latest batch only)


@app.post("/runs", dependencies=[Depends(_auth)])
def runs_start(body: RunIn | None = None):
    """Start a Devin session that runs one cycle (`mkt daily`, same as `mkt devin kickoff`): analyse
    the sources and our posts, write scripts, render clips. A cycle posts nothing; posting is the
    Post button on each clip (POST /renders/{script_id}/post), one approved clip at a time."""
    from .orchestrator import DEFAULT_REPO, DevinClient, daily_prompt

    body = body or RunIn()

    s = DevinClient().create_session(
        daily_prompt(
            body.niche,
            body.tags,
            body.product,
            body.renders,
            body.resolution,
            refs=body.refs,
            product_tags=body.product_tags,
            mode=body.mode,
            api_url=API_PUBLIC_URL,
        ),
        title=f"mkt {body.mode if body.mode != 'full' else 'cycle'} {body.niche} {time.strftime('%Y-%m-%d')}",
        tags=["marketing-agent", body.niche, "api"],
        repos=[DEFAULT_REPO],
        max_acu_limit=body.max_acu,
    )
    rid = _store().insert(
        "runs",
        {
            "created_at": int(time.time()),
            "session_id": s["session_id"],
            "url": s["url"],
            "niche": body.niche,
            "product": body.product,
            "note": {
                "research": "research only, no clips",
                "render": f"clips only: {body.renders} at {body.resolution}",
            }.get(body.mode, f"{body.renders} clips at {body.resolution}"),
        },
    )
    return {"ok": True, "id": rid, "session_id": s["session_id"], "url": s["url"]}


@app.get("/db")
def db_export():
    """The whole SQLite file, so a daily session can start from the API's state."""
    path = settings.db_path
    if not path.exists():
        raise HTTPException(404, "no db yet")
    return FileResponse(path, media_type="application/octet-stream", filename="mkt.sqlite")


@app.post("/db", dependencies=[Depends(_auth)])
async def db_import(request: Request):
    """Replace the API's SQLite with the uploaded file (raw body). The daily session pushes its
    finished db here, so the API is the source of truth between runs."""
    body = await request.body()
    if not body.startswith(b"SQLite format 3"):
        raise HTTPException(400, "body is not a SQLite file")
    path = settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".sqlite.tmp")
    tmp.write_bytes(body)
    tmp.replace(path)
    return {"ok": True, "bytes": len(body)}


class BrowserSession(BaseModel):
    cookies: list[dict]


def _session_cipher():
    from cryptography.fernet import Fernet

    key = os.environ.get("MKT_SESSION_KEY")
    if not key:
        raise HTTPException(503, "MKT_SESSION_KEY not configured; the browser session is off")
    return Fernet(key)


def _session_path() -> Path:
    return settings.db_path.parent / "browser_session.enc"


@app.put("/browser/session", dependencies=[Depends(_auth)])
def browser_session_save(body: BrowserSession):
    """`mkt browser save`: the signed-in TikTok cookies, kept encrypted so every poster session is
    the same browser to TikTok instead of a new login."""
    if not body.cookies:
        raise HTTPException(400, "no cookies")
    path = _session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = _session_cipher().encrypt(json.dumps({"cookies": body.cookies}).encode())
    path.write_bytes(blob)
    return {"ok": True, "cookies": len(body.cookies), "saved_at": int(time.time())}


@app.get("/browser/session", dependencies=[Depends(_auth)])
def browser_session_load():
    """`mkt browser restore`: the saved session, decrypted for the token holder."""
    path = _session_path()
    if not path.exists():
        raise HTTPException(404, "no saved session")
    from cryptography.fernet import InvalidToken

    try:
        data = json.loads(_session_cipher().decrypt(path.read_bytes()))
    except InvalidToken:
        raise HTTPException(500, "saved session does not decrypt with this key") from None
    data["saved_at"] = int(path.stat().st_mtime)
    return data


@app.post("/repoll", dependencies=[Depends(_auth)])
def repoll_cohort(max_age_days: float = 8.0, niche: str | None = None):
    """Re-poll every tracked video inside the window and rebuild features. The site's
    "Check post performance" button calls this; the cycle itself re-polls as its first stage."""
    store = _store()
    res = repoll(store, max_age_days, niche)
    res["features"] = build_features(store, niche)
    save_findings(store, analyze(store))
    return res


@app.get("/features")
def features_list(niche: str = DEFAULT_NICHE):
    return features(_store(), niche, group="reference")


@app.get("/videos/{video_id}")
def video_detail(video_id: str):
    """Everything we know about one video: the row, its observation curve, tags with the
    classifier's run record, its feature row and the creator's baseline snapshot."""
    store = _store()
    rows = store.rows("SELECT * FROM videos WHERE id=?", (video_id,))
    if not rows:
        raise HTTPException(404, "no video")
    v = rows[0]
    v["hashtags"] = json.loads(v.get("hashtags") or "[]")
    tag_rows = store.rows(
        "SELECT model, tagged_at, payload FROM tags WHERE video_id=?", (video_id,)
    )
    feat = store.rows("SELECT payload FROM features WHERE video_id=?", (video_id,))
    return {
        "video": v,
        "observations": store.rows(
            "SELECT * FROM observations WHERE video_id=? ORDER BY observed_at", (video_id,)
        ),
        "tags": json.loads(tag_rows[0]["payload"]) if tag_rows else None,
        "tagged_at": tag_rows[0]["tagged_at"] if tag_rows else None,
        "features": json.loads(feat[0]["payload"]) if feat else None,
        "creator": latest_snapshot(store, v["author"]),
    }


@app.get("/creators/{handle}")
def creator_detail(handle: str):
    """An account's videos with their latest stats, plus its baseline snapshots over time."""
    store = _store()
    vids = store.rows(
        """SELECT v.id, v.url, v.desc, v.create_time, v.duration, v.music, v.source_tag, v.niche,
                  v.cohort_at, o.views, o.likes, o.comments, o.shares
           FROM videos v JOIN observations o ON o.video_id=v.id
           WHERE v.author=? AND o.observed_at=(SELECT MAX(observed_at) FROM observations WHERE video_id=v.id)
           ORDER BY v.create_time DESC""",
        (handle,),
    )
    if not vids:
        raise HTTPException(404, "no creator")
    feats = {f["video_id"]: f for f in features(store) if f["author"] == handle}
    for v in vids:
        v["lift_72h"] = feats.get(v["id"], {}).get("lift_72h")
    return {
        "handle": handle,
        "videos": vids,
        "snapshots": store.rows(
            "SELECT * FROM creator_snapshots WHERE author=? ORDER BY taken_at", (handle,)
        ),
    }


@app.get("/findings")
def findings_latest():
    """Latest controlled-effect tables, or a `collecting` status while fewer than MIN_N panel
    videos are scored (a day old with a view count); the 72h ETA is kept for the slower outcomes."""
    f = latest_findings(_store())
    if not f:
        return {
            "status": {"videos": 0, "reached": {"72h": 0, "scored": 0}},
            "fits": {},
            "collecting": True,
        }
    f["collecting"] = f["status"]["reached"].get("scored", 0) < f["min_n"]
    return f


@app.post("/analyze", dependencies=[Depends(_auth)])
def analyze_now(niche: str | None = None):
    store = _store()
    res = analyze(store, [niche or DEFAULT_NICHE])
    save_findings(store, res)
    return res["status"]


class PostIn(BaseModel):
    """A post a person made from one of our accounts: its TikTok link and, ideally, the caption
    used, so it links to its script even before TikTok makes it public."""

    url: str
    caption: str = ""
    script_id: int | None = None  # the poster session passes the clip it uploaded


class TagRow(BaseModel):
    video_id: str
    model: str
    payload: dict


@app.post("/tags", dependencies=[Depends(_auth)])
def tags_import(rows: list[TagRow]):
    """Merge labels made on another machine (the video model's rubric pass) into the db, row by
    row, without replacing the whole file the way POST /db does."""
    store = _store()
    ids = [r.video_id for r in rows]
    marks = ",".join("?" * len(ids))
    known = (
        {r["id"] for r in store.rows(f"SELECT id FROM videos WHERE id IN ({marks})", tuple(ids))}
        if ids
        else set()
    )
    for r in rows:
        if r.video_id in known:
            store.save_tags(r.video_id, r.model, r.payload)
    return {
        "saved": sum(r.video_id in known for r in rows),
        "unknown": [i for i in ids if i not in known],
    }


@app.get("/rubric")
def rubric_variables():
    """The video rubric: every variable the video model records, in the order it asks them."""
    from .classifier import rubric

    return {"version": rubric.version(), "variables": rubric.variables()}


@app.post("/ours/posts", dependencies=[Depends(_auth)])
def ours_add_post(body: PostIn):
    """Register a post we made so the re-poll tracks its views and the picker learns from it."""
    from .own import add_post

    store = _store()
    try:
        res = add_post(store, body.url, body.caption, niche=DEFAULT_NICHE, script_id=body.script_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if res.get("script_id"):
        _finish_post_runs(store, res["script_id"])
        copy_to_tags(store, res["id"], res["script_id"])
    return res


def _finish_post_runs(store: Store, script_id: int) -> None:
    """A post request's run row is done once its clip is registered; otherwise the Learnings page
    keeps treating it as a cycle still going and disables its buttons."""
    with store.conn() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(runs)")}
        for col, typ in (("status", "TEXT"), ("stages", "TEXT"), ("finished_at", "INTEGER")):
            if col not in cols:
                c.execute(f"ALTER TABLE runs ADD COLUMN {col} {typ}")
        c.execute(
            """UPDATE runs SET finished_at=?, status='ok'
               WHERE finished_at IS NULL AND (note=? OR note LIKE ?)""",
            (
                int(time.time()),
                f"post s{script_id} from @{CAMPAIGN.account.handle}",
                f"post s{script_id} from @% (try %",
            ),
        )


@app.get("/ours")
def ours():
    """Our own posts with script, concept, baseline and lift, plus the per-concept reward the
    picker is currently using and the accounts we watch."""
    store = _store()
    return {
        "accounts": own_accounts(store),
        "posts": own_posts(store),
        "rewards": own_rewards(store),
    }
