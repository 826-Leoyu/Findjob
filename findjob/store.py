"""职位入库与跨来源去重。"""

import re
import sqlite3
from dataclasses import dataclass
from typing import Literal

COMPANY_SUFFIXES = {"inc", "incorporated", "ltd", "limited", "llc", "llp", "corp", "corporation", "co", "ltee", "ltée"}


def _words(s: str) -> list[str]:
    return re.findall(r"\w+", s.lower())


def dedup_key(company: str, title: str, location: str) -> str:
    """规范化的 公司|职位名|城市。"""
    company_words = _words(company)
    while company_words and company_words[-1] in COMPANY_SUFFIXES:
        company_words.pop()
    city = re.split(r"[,(]", location, maxsplit=1)[0]
    return "|".join(" ".join(w) for w in (company_words, _words(title), _words(city)))


@dataclass
class Job:
    source: str
    source_id: str
    url: str
    title: str
    company: str
    location: str
    remote: bool | None
    posted_at: str | None
    description: str


def save(conn: sqlite3.Connection, job: Job, profile: str) -> Literal["new", "seen", "dup"]:
    """new = 新职位；seen = 这个来源已记录过；dup = 别的来源已有同一职位，只追加来源。"""
    if conn.execute("SELECT 1 FROM job_sources WHERE source = ? AND url = ?",
                    (job.source, job.url)).fetchone():
        return "seen"
    key = dedup_key(job.company, job.title, job.location)
    with conn:
        row = conn.execute("SELECT id FROM jobs WHERE dedup_key = ?", (key,)).fetchone()
        if row:
            job_id, result = row["id"], "dup"
        else:
            job_id = conn.execute(
                """INSERT INTO jobs (dedup_key, source, source_id, url, title, company, location,
                                     remote, posted_at, description, profile)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (key, job.source, job.source_id, job.url, job.title, job.company, job.location,
                 None if job.remote is None else int(job.remote), job.posted_at, job.description, profile),
            ).lastrowid
            conn.execute("INSERT INTO status_history (job_id, status) VALUES (?, 'new')", (job_id,))
            result = "new"
        conn.execute("INSERT INTO job_sources (job_id, source, source_id, url) VALUES (?, ?, ?, ?)",
                     (job_id, job.source, job.source_id, job.url))
    return result


def known_source_ids(conn: sqlite3.Connection, source: str) -> set[str]:
    rows = conn.execute("SELECT source_id FROM job_sources WHERE source = ?", (source,))
    return {r["source_id"] for r in rows}
