"""粗筛：按配置的排除词与经验年限上限过滤、按关键词给粗分。无 LLM、不联网。"""

import json
import re
import sqlite3
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field

from .jobbank import PROVINCES, split_locations


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


# Job Bank 标准行 "Experience: <X>" 的枚举值 → 要求的最少年数
JOBBANK_EXPERIENCE = {
    "no experience (will train)": 0,
    "experience an asset": 0,
    "1 to less than 7 months": 0,
    "7 months to less than 1 year": 0,
    "1 year to less than 2 years": 1,
    "2 years to less than 3 years": 2,
    "3 years to less than 5 years": 3,
    "5 years or more": 5,
    "ten or more years": 10,
}
JOBBANK_LINE_RE = re.compile(
    r"\bExperience:\s*(" + "|".join(re.escape(v) for v in JOBBANK_EXPERIENCE) + ")",
    re.IGNORECASE)
# 自由文本里的年限写法，第 1 组是要求的最少年数
FREE_TEXT_YEARS_RES = [re.compile(p, re.IGNORECASE) for p in (
    r"\b(\d{1,2})\s*\+\s*years?\b",              # 5+ years
    r"\b(\d{1,2})\s+years?\s+or\s+more\b",          # 3 years or more
    r"\b(\d{1,2})\s*[-–]\s*\d{1,2}\s+years?\b",     # 3-5 years（取下限）
    r"\bminimum\s+of\s+(\d{1,2})\s+years?\b",       # minimum of 3 years
)]
EXPERIENCE_WORD_RE = re.compile(r"\b(experienc\w*|professional)\b", re.IGNORECASE)
EXPERIENCE_WINDOW_BEFORE, EXPERIENCE_WINDOW_AFTER = 40, 80  # 年限前后多少个字符内须出现 experience / professional


def _near_experience_word(text: str, match: re.Match) -> bool:
    window = text[max(0, match.start() - EXPERIENCE_WINDOW_BEFORE):match.end() + EXPERIENCE_WINDOW_AFTER]
    return EXPERIENCE_WORD_RE.search(window) is not None


def required_experience(description: str) -> int | None:
    """JD 要求的最少经验年数；没有可识别的年限时为 None。"""
    years = [JOBBANK_EXPERIENCE[m.group(1).lower()] for m in JOBBANK_LINE_RE.finditer(description)]
    for pattern in FREE_TEXT_YEARS_RES:
        for m in pattern.finditer(description):
            if _near_experience_word(description, m):
                years.append(int(m.group(1)))
    return max(years, default=None)


# 多伦多的行政区 → Toronto（小写）
CITY_ALIASES = {borough: "toronto" for borough in ("north york", "scarborough", "etobicoke", "east york", "york")}


def _city_key(location: str) -> str:
    city = location.partition(",")[0].strip().lower()
    return CITY_ALIASES.get(city, city)


# remote 字段为空时，职位名或 JD 中出现这些表述即视为远程
REMOTE_PHRASES = ("fully remote", "100% remote", "remote position", "remote role")


def _is_remote(remote: int | None, title: str, description: str) -> bool:
    """remote 字段为 1，或为空但有明确的远程表述。补判结果不回写。"""
    if remote is not None:
        return bool(remote)
    return any(_contains(text, phrase) for phrase in REMOTE_PHRASES for text in (title, description))


def _check_location(job: Mapping, profile: Mapping, remote: bool) -> tuple[str | None, list[str]]:
    """返回（过滤原因，标记）；地点符合时原因为 None。"""
    if remote and profile["remote"]:
        return None, []
    location = job["location"] or ""
    city, _, province = (part.strip() for part in location.partition(","))
    if not city or province.upper() not in PROVINCES:  # "Various locations" 等无法解析的地点
        return None, ["location_unknown"]
    provinces, cities = split_locations(profile["locations"])
    if province.upper() in provinces or _city_key(location) in {_city_key(c) for c in cities}:
        return None, []
    return f"location: {city}", []


def screen(job: Mapping, profile: Mapping) -> Verdict:
    """job 需含 title（原始职位名）、description、location 与 remote。"""
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
    years = required_experience(description)
    if years is not None and years > profile["max_experience_years"]:
        return Verdict(keep=False, reason=f"experience: {years}", coarse_score=score)
    reason, flags = _check_location(job, profile, _is_remote(job["remote"], title, description))
    if reason is not None:
        return Verdict(keep=False, reason=reason, coarse_score=score)
    return Verdict(keep=True, reason=None, coarse_score=score, flags=flags)


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
