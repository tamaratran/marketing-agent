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

from .config import settings
from .creators.ops import add_creator, create_brief, creator_report, payouts, record_post
from .policy import concept_scores, winning_traits
from .scoreboard import build
from .store import Store


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
    sb = build(store)
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
def scripts(days: int = 7, product: str | None = None, limit: int = 100):
    since = int(time.time()) - days * 86400
    sql = """SELECT s.id, s.concept_id, c.name concept, s.product, s.created_at, s.hook,
                    s.demo_score, s.payload FROM scripts s LEFT JOIN concepts c ON c.id=s.concept_id
             WHERE s.created_at>=?"""
    args: list = [since]
    if product:
        sql += " AND s.product=?"
        args.append(product)
    sql += " ORDER BY s.created_at DESC, s.demo_score DESC LIMIT ?"
    args.append(limit)
    out = []
    for r in _store().rows(sql, tuple(args)):
        payload = json.loads(r.pop("payload") or "{}")
        out.append({**r, "captions": payload.get("captions"), "body": payload.get("body")})
    return out


@app.get("/renders")
def renders(limit: int = 50):
    return _store().rows(
        """SELECT r.id, r.script_id, r.created_at, r.model, r.cost_usd, r.final_path, s.hook
           FROM renders r JOIN scripts s ON s.id=r.script_id
           WHERE r.final_path IS NOT NULL ORDER BY r.created_at DESC LIMIT ?""",
        (limit,),
    )


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
