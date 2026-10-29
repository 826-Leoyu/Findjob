import sqlite3
from pathlib import Path

from .paths import DB_PATH

# 状态流转：new -> scored -> tailored -> applied -> interview / rejected
STATUSES = ("new", "scored", "tailored", "applied", "interview", "rejected", "skipped")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY,
    dedup_key     TEXT NOT NULL UNIQUE,      -- 规范化的 公司|标题|地点，用于跨来源去重
    source        TEXT NOT NULL,             -- jobbank / greenhouse / lever / ashby / jobspy:indeed ...
    source_id     TEXT,
    url           TEXT NOT NULL,
    title         TEXT NOT NULL,
    company       TEXT NOT NULL,
    location      TEXT,
    remote        INTEGER,                   -- 1 = 可在加拿大远程
    posted_at     TEXT,
    description   TEXT,
    profile       TEXT,                      -- 命中的搜索配置名
    coarse_score  REAL,                      -- Python 粗筛分
    fine_score    INTEGER,                   -- Claude 精评分 0-100
    fine_notes    TEXT,                      -- 精评：匹配点 / 缺口 / 风险（JSON）
    flags         TEXT,                      -- 例如 ["requires_pr"]（JSON）
    status        TEXT NOT NULL DEFAULT 'new'
                  CHECK (status IN ({", ".join(f"'{s}'" for s in STATUSES)})),
    resume_path   TEXT,
    cover_letter_path TEXT,
    first_seen    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS job_sources (
    job_id     INTEGER NOT NULL REFERENCES jobs(id),
    source     TEXT NOT NULL,
    source_id  TEXT,
    url        TEXT NOT NULL,
    seen_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (source, url)
);

CREATE TABLE IF NOT EXISTS status_history (
    id         INTEGER PRIMARY KEY,
    job_id     INTEGER NOT NULL REFERENCES jobs(id),
    status     TEXT NOT NULL,
    note       TEXT,
    changed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: Path = DB_PATH) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)
