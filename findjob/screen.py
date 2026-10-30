"""粗筛：按配置的排除词过滤、按关键词给粗分。无 LLM、不联网。"""

import json
import re
import sqlite3
from collections import Counter
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


@dataclass
class ScreenRun:
    results: list[tuple[sqlite3.Row, Verdict]]
    unmatched: Counter = field(default_factory=Counter)  # 配置不可用而跳过的职位数，按配置名


def screen_pending(conn: sqlite3.Connection, profiles: Mapping[str, Mapping],
                   rescreen: bool = False, only_profile: str | None = None) -> ScreenRun:
    """筛选待筛选的职位（status = 'new' 且尚无粗分），结果写回库里。

    profiles 是可用的配置，按 name 索引；职位记录的配置不在其中时跳过。
    rescreen 时重新筛选全部 new 与 skipped 职位，状态变化各记一条 status_history。
    """
    where = "status IN ('new', 'skipped')" if rescreen else "status = 'new' AND coarse_score IS NULL"
    params: tuple = ()
    if only_profile is not None:
        where += " AND profile = ?"
        params = (only_profile,)
    rows = conn.execute(f"SELECT * FROM jobs WHERE {where} ORDER BY id", params).fetchall()
    run = ScreenRun(results=[])
    with conn:
        for row in rows:
            profile = profiles.get(row["profile"])
            if profile is None:
                run.unmatched[row["profile"]] += 1
                continue
            verdict = screen(row, profile)
            status = "new" if verdict.keep else "skipped"
            conn.execute(
                """UPDATE jobs SET status = ?, coarse_score = ?, flags = ?, updated_at = datetime('now')
                   WHERE id = ?""",
                (status, verdict.coarse_score, json.dumps(verdict.flags), row["id"]),
            )
            if status != row["status"]:
                note = verdict.reason if status == "skipped" else "重新筛选后保留"
                conn.execute("INSERT INTO status_history (job_id, status, note) VALUES (?, ?, ?)",
                             (row["id"], status, note))
            run.results.append((row, verdict))
    return run
