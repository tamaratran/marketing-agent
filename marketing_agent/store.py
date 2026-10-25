"""SQLite store. One row per video, one row per observation (so views-over-time is a signal)."""

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
  id TEXT PRIMARY KEY,
  url TEXT,
  author TEXT,
  followers INTEGER,
  create_time INTEGER,
  duration INTEGER,
  desc TEXT,
  music TEXT,
  hashtags TEXT,
  source_tag TEXT,
  first_seen INTEGER,
  local_path TEXT
);
CREATE TABLE IF NOT EXISTS observations (
  video_id TEXT,
  observed_at INTEGER,
  views INTEGER, likes INTEGER, comments INTEGER, shares INTEGER, saves INTEGER,
  PRIMARY KEY (video_id, observed_at)
);
CREATE TABLE IF NOT EXISTS tags (
  video_id TEXT PRIMARY KEY,
  model TEXT,
  tagged_at INTEGER,
  payload TEXT
);
CREATE TABLE IF NOT EXISTS concepts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  niche TEXT,
  created_at INTEGER,
  name TEXT,
  description TEXT,
  video_ids TEXT,
  early_score REAL,
  payload TEXT
);
CREATE TABLE IF NOT EXISTS scripts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  concept_id INTEGER,
  product TEXT,
  created_at INTEGER,
  hook TEXT,
  body TEXT,
  demo_score INTEGER,
  payload TEXT
);
CREATE TABLE IF NOT EXISTS renders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  script_id INTEGER,
  created_at INTEGER,
  model TEXT,
  prompt TEXT,
  raw_path TEXT,
  final_path TEXT,
  cost_usd REAL,
  payload TEXT
);
CREATE TABLE IF NOT EXISTS creators (
  handle TEXT PRIMARY KEY,
  platform TEXT,
  channel TEXT,
  rate_per_1k REAL,
  followers INTEGER,
  added_at INTEGER,
  notes TEXT
);
CREATE TABLE IF NOT EXISTS briefs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at INTEGER,
  product TEXT,
  script_ids TEXT,
  rate_per_1k REAL,
  cap_usd REAL,
  deadline_days INTEGER,
  body TEXT,
  status TEXT
);
CREATE TABLE IF NOT EXISTS posts (
  video_id TEXT PRIMARY KEY,
  creator TEXT,
  brief_id INTEGER,
  script_id INTEGER,
  posted_at INTEGER,
  url TEXT
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at INTEGER,
  session_id TEXT,
  url TEXT,
  niche TEXT,
  product TEXT,
  note TEXT
);
CREATE TABLE IF NOT EXISTS niche_tags (
  niche TEXT,
  tag TEXT,
  PRIMARY KEY (niche, tag)
);
CREATE TABLE IF NOT EXISTS payouts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  creator TEXT,
  video_id TEXT,
  views INTEGER,
  amount_usd REAL,
  computed_at INTEGER,
  paid_at INTEGER
);
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    def upsert_video(self, v: dict, observed_at: int | None = None) -> None:
        now = observed_at or int(time.time())
        with self.conn() as c:
            c.execute(
                """INSERT INTO videos (id,url,author,followers,create_time,duration,desc,music,hashtags,source_tag,first_seen)
                   VALUES (:id,:url,:author,:followers,:create_time,:duration,:desc,:music,:hashtags,:source_tag,:first_seen)
                   ON CONFLICT(id) DO UPDATE SET followers=excluded.followers, desc=excluded.desc, music=excluded.music""",
                {**v, "hashtags": json.dumps(v.get("hashtags", [])), "first_seen": now},
            )
            c.execute(
                """INSERT OR REPLACE INTO observations VALUES (?,?,?,?,?,?,?)""",
                (
                    v["id"],
                    now,
                    v.get("views"),
                    v.get("likes"),
                    v.get("comments"),
                    v.get("shares"),
                    v.get("saves"),
                ),
            )

    def set_local_path(self, video_id: str, path: str) -> None:
        with self.conn() as c:
            c.execute("UPDATE videos SET local_path=? WHERE id=?", (path, video_id))

    def save_tags(self, video_id: str, model: str, payload: dict) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO tags VALUES (?,?,?,?)",
                (video_id, model, int(time.time()), json.dumps(payload)),
            )

    def latest(self, tag: str | None = None, limit: int = 500) -> list[dict]:
        """Videos with their most recent observation, newest-first."""
        q = """SELECT v.*, o.views, o.likes, o.comments, o.shares, o.saves, o.observed_at
               FROM videos v JOIN observations o ON o.video_id=v.id
               WHERE o.observed_at = (SELECT MAX(observed_at) FROM observations WHERE video_id=v.id)"""
        args: list = []
        if tag:
            q += " AND v.source_tag=?"
            args.append(tag)
        q += " ORDER BY v.create_time DESC LIMIT ?"
        args.append(limit)
        with self.conn() as c:
            return [dict(r) for r in c.execute(q, args)]

    def set_niche_tags(self, niche: str, tags: list[str]) -> None:
        """Remember which hashtags were scraped for a niche, so per-niche views can exclude the
        other niches' videos."""
        with self.conn() as c:
            c.executemany(
                "INSERT OR IGNORE INTO niche_tags (niche, tag) VALUES (?, ?)",
                [(niche, t) for t in tags],
            )

    def niche_tags(self, niche: str) -> list[str]:
        with self.conn() as c:
            return [r[0] for r in c.execute("SELECT tag FROM niche_tags WHERE niche=?", (niche,))]

    def untagged(self, limit: int = 50) -> list[dict]:
        with self.conn() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM videos v WHERE local_path IS NOT NULL AND NOT EXISTS (SELECT 1 FROM tags t WHERE t.video_id=v.id) LIMIT ?",
                    (limit,),
                )
            ]

    def tags_for(self, video_ids: list[str]) -> dict[str, dict]:
        if not video_ids:
            return {}
        qs = ",".join("?" * len(video_ids))
        with self.conn() as c:
            return {
                r["video_id"]: json.loads(r["payload"])
                for r in c.execute(
                    f"SELECT video_id, payload FROM tags WHERE video_id IN ({qs})", video_ids
                )
            }

    def insert(self, table: str, row: dict) -> int:
        cols = ",".join(row)
        qs = ",".join("?" * len(row))
        with self.conn() as c:
            cur = c.execute(f"INSERT INTO {table} ({cols}) VALUES ({qs})", list(row.values()))
            return cur.lastrowid

    def rows(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute(sql, args)]
