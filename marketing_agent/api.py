"""HTTP backend over the same SQLite the CLI uses. Reads are open; writes need
`Authorization: Bearer $MKT_API_TOKEN`. Run: uvicorn marketing_agent.api:app --port 8080."""

import json
import os
import time
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .cohort import build_features, features, latest_snapshot, repoll
from .config import settings
from .creators.ops import add_creator, create_brief, creator_report, payouts, record_post
from .policy import concept_scores, winning_traits
from .scoreboard import build
from .store import Store
from .video.edit import strip_label


def _store() -> Store:
    return Store(settings.db_path)


def _auth(authorization: str | None = Header(default=None)) -> None:
    token = os.environ.get("MKT_API_TOKEN")
    if not token:
        raise HTTPException(503, "MKT_API_TOKEN not configured; writes disabled")
    if authorization != f"Bearer {token}":
        raise HTTPException(401, "bad token")


app = FastAPI(title="marketing-agent", version="0.1")
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
def overview(niche: str = "wearables"):
    store = _store()
    sb = build(store, tags=store.niche_tags(niche) or None)
    spent = sum(r["cost_usd"] or 0 for r in store.rows("SELECT cost_usd FROM renders"))
    pays = payouts(store)
    return {
        "niche": niche,
        "videos": len(sb["videos"]),
        "scored": sb["n_scored"],
        "tagged": sb["n_tagged"],
        "concepts": len(concept_scores(store, niche)),
        "spent_usd": round(spent, 2),
        "owed_usd": round(sum(p["owed_usd"] for p in pays), 2),
        "winning": winning_traits(store),
        "hooks": sb["hooks"][:8],
        "styles": sb["styles"][:8],
        "concept_rank": sb["concepts"][:8],
        "stuck_accounts": sb["stuck_accounts"],
        "top_videos": [v for v in sb["videos"] if v.get("hook_type")][:20],
    }


@app.get("/concepts")
def concepts(niche: str = "wearables"):
    return concept_scores(_store(), niche)


@app.get("/scripts")
def scripts(days: int = 7, product: str | None = None, limit: int = 100, niche: str = "wearables"):
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
        out.append({**r, "captions": payload.get("captions"), "body": payload.get("body")})
    return out


@app.get("/renders")
def renders(limit: int = 50, niche: str = "wearables"):
    """Real clips only: the stub provider's colour cards are for offline tests, not the site."""
    rows = _store().rows(
        """SELECT r.id, r.script_id, r.created_at, r.model, r.cost_usd, r.final_path, s.hook
           FROM renders r JOIN scripts s ON s.id=r.script_id JOIN concepts c ON c.id=s.concept_id
           WHERE r.final_path IS NOT NULL AND r.model!='stub' AND c.niche=?
           ORDER BY r.created_at DESC LIMIT ?""",
        (niche, limit),
    )
    for r in rows:
        r["hook"] = strip_label(r["hook"] or "")
    return rows


@app.get("/renders/{render_id}/file")
def render_file(render_id: int):
    rows = _store().rows("SELECT final_path FROM renders WHERE id=?", (render_id,))
    if not rows or not rows[0]["final_path"] or not Path(rows[0]["final_path"]).exists():
        raise HTTPException(404, "no file")
    return FileResponse(rows[0]["final_path"], media_type="video/mp4")


@app.get("/creators")
def creators(stall_days: int = 7):
    return creator_report(_store(), stall_days)


class CreatorIn(BaseModel):
    handle: str
    channel: str = "discord"
    rate_per_1k: float = 1.0
    followers: int | None = None
    notes: str = ""


@app.post("/creators", dependencies=[Depends(_auth)])
def creators_add(body: CreatorIn):
    add_creator(_store(), body.handle, body.channel, body.rate_per_1k, body.followers, body.notes)
    return {"ok": True, "handle": body.handle.lstrip("@")}


@app.get("/briefs")
def briefs():
    return _store().rows("SELECT * FROM briefs ORDER BY id DESC")


class BriefIn(BaseModel):
    product: str
    script_ids: list[int] = Field(min_length=1)
    rate_per_1k: float = 1.0
    cap_usd: float = 200.0
    deadline_days: int = 5


@app.post("/briefs", dependencies=[Depends(_auth)])
def briefs_create(body: BriefIn):
    return create_brief(
        _store(), body.product, body.script_ids, body.rate_per_1k, body.cap_usd, body.deadline_days
    )


@app.post("/briefs/{brief_id}/status", dependencies=[Depends(_auth)])
def briefs_status(brief_id: int, status: str):
    """draft -> approved -> posted; nothing is sent anywhere, this records the human decision."""
    if status not in {"draft", "approved", "posted", "closed"}:
        raise HTTPException(400, "status must be draft, approved, posted or closed")
    with _store().conn() as c:
        if not c.execute("UPDATE briefs SET status=? WHERE id=?", (status, brief_id)).rowcount:
            raise HTTPException(404, "no brief")
    return {"ok": True, "id": brief_id, "status": status}


@app.get("/posts")
def posts():
    return _store().rows(
        """SELECT p.*, (SELECT views FROM observations o WHERE o.video_id=p.video_id
                        ORDER BY observed_at DESC LIMIT 1) views FROM posts p ORDER BY posted_at DESC"""
    )


class PostIn(BaseModel):
    creator: str
    url: str
    brief_id: int | None = None
    script_id: int | None = None


@app.post("/posts", dependencies=[Depends(_auth)])
def posts_add(body: PostIn):
    from .research.tiktok_browser import poll_public_stats

    try:
        stats = poll_public_stats(body.url)
    except Exception:  # noqa: BLE001 - stats are a nice-to-have at record time
        stats = None
    vid = record_post(_store(), body.creator, body.url, body.brief_id, body.script_id, stats)
    return {"ok": True, "video_id": vid, "polled": bool(stats)}


@app.get("/payouts")
def payouts_list(min_age_days: int = 7):
    return payouts(_store(), min_age_days)


class PaidIn(BaseModel):
    amount_usd: float
    views: int | None = None


@app.post("/payouts/{video_id}/paid", dependencies=[Depends(_auth)])
def payouts_paid(video_id: str, body: PaidIn):
    store = _store()
    post = store.rows("SELECT creator FROM posts WHERE video_id=?", (video_id,))
    if not post:
        raise HTTPException(404, "no post")
    now = int(time.time())
    pid = store.insert(
        "payouts",
        {
            "creator": post[0]["creator"],
            "video_id": video_id,
            "views": body.views,
            "amount_usd": body.amount_usd,
            "computed_at": now,
            "paid_at": now,
        },
    )
    return {"ok": True, "id": pid}


@app.get("/runs")
def runs(limit: int = 30):
    return _store().rows("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))


class RunIn(BaseModel):
    niche: str = "wearables"
    tags: list[str] = ["smartring", "whoop", "ouraring"]
    product: str
    renders: int = 1
    max_acu: int = 10


@app.post("/runs", dependencies=[Depends(_auth)])
def runs_start(body: RunIn):
    """Start a Devin session that runs `mkt daily` (same as `mkt devin kickoff`)."""
    from .orchestrator import DEFAULT_REPO, DevinClient, daily_prompt

    s = DevinClient().create_session(
        daily_prompt(body.niche, body.tags, body.product, body.renders),
        title=f"mkt daily {body.niche} {time.strftime('%Y-%m-%d')}",
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
            "note": "",
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


@app.post("/repoll", dependencies=[Depends(_auth)])
def repoll_cohort(max_age_days: float = 8.0, niche: str | None = None):
    """Re-poll every cohort video inside the window and rebuild features. The 2-hourly Modal cron
    calls this so the curves are recorded here, race-free, rather than by replacing the db."""
    store = _store()
    res = repoll(store, max_age_days, niche)
    res["features"] = build_features(store, niche)
    return res


@app.get("/features")
def features_list(niche: str = "wearables"):
    return features(_store(), niche)


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
