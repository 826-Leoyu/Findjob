"""粗筛：按配置的排除词过滤、按关键词给粗分。无 LLM、不联网。"""

import json
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass
class Verdict:
    keep: bool
    reason: str | None        # "类别: 详情"，例如 "exclude: senior"；保留时为 None
    coarse_score: int
    flags: list[str] = field(default_factory=list)


def _contains(text: str, phrase: str) -> bool:
    """整词匹配，不区分大小写；短语里的标点按原样匹配，空白可宽松对应。"""
    pattern = r"\s+".join(re.escape(w) for w in phrase.split())
    return re.search(rf"(?<!\w){pattern}(?!\w)", text, re.IGNORECASE) is not None


def screen(job: Mapping, profile: Mapping) -> Verdict:
    """job 需含 title（原始职位名）与 description。"""
    title = job["title"] or ""
    description = job["description"] or ""

    score = 0
    for keyword in profile["keywords"]:
        if _contains(title, keyword):
            score += 2
        elif _contains(description, keyword):
            score += 1

    for word in profile["exclude"]:
        if _contains(title, word):
            return Verdict(keep=False, reason=f"exclude: {word}", coarse_score=score)
    return Verdict(keep=True, reason=None, coarse_score=score)


def screen_pending(conn: sqlite3.Connection, profiles: Mapping[str, Mapping],
                   log=print) -> list[tuple[sqlite3.Row, Verdict]]:
    """筛选所有 status = 'new' 且尚无粗分的职位，结果写回库里。profiles 按 name 索引。"""
    rows = conn.execute(
        "SELECT * FROM jobs WHERE status = 'new' AND coarse_score IS NULL ORDER BY id").fetchall()
    results = []
    missing: set[str] = set()
    with conn:
        for row in rows:
            profile = profiles.get(row["profile"])
            if profile is None:
                missing.add(row["profile"])
                continue
            verdict = screen(row, profile)
            status = "new" if verdict.keep else "skipped"
            conn.execute(
                """UPDATE jobs SET status = ?, coarse_score = ?, flags = ?, updated_at = datetime('now')
                   WHERE id = ?""",
                (status, verdict.coarse_score, json.dumps(verdict.flags), row["id"]),
            )
            if not verdict.keep:
                conn.execute("INSERT INTO status_history (job_id, status, note) VALUES (?, 'skipped', ?)",
                             (row["id"], verdict.reason))
            results.append((row, verdict))
    for name in sorted(missing, key=str):
        log(f"[screen] 找不到配置 {name!r}，相关职位留待下次")
    return results
