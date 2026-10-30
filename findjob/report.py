"""粗筛日报（Markdown）。"""

import datetime
import sqlite3
from collections import Counter
from pathlib import Path

from .screen import Verdict


def render_report(results: list[tuple[sqlite3.Row, Verdict]], day: datetime.date) -> str:
    kept = sorted(((job, v) for job, v in results if v.keep), key=lambda jv: -jv[1].coarse_score)
    reasons = Counter(v.reason for _, v in results if not v.keep)

    lines = [f"# 职位日报 {day.isoformat()}", "", f"## 保留职位（{len(kept)}）", ""]
    for i, (job, verdict) in enumerate(kept, 1):
        where = "远程" if job["remote"] else (job["location"] or "地点未知")
        flags = "、".join(verdict.flags) or "无"
        lines.append(f"{i}. **{job['title']}** — {job['company']} · {where} · "
                     f"发布 {job['posted_at'] or '未知'} · 粗分 {verdict.coarse_score} · 标记 {flags}  ")
        lines.append(f"   <{job['url']}>")
    if not kept:
        lines.append("本次没有保留的职位。")

    lines += ["", "## 统计", "",
              f"- 处理 {len(results)}，保留 {len(kept)}，过滤 {len(results) - len(kept)}"]
    for reason, n in reasons.most_common():
        lines.append(f"  - {reason}：{n}")
    return "\n".join(lines) + "\n"


def write_report(results: list[tuple[sqlite3.Row, Verdict]], reports_dir: Path, day: datetime.date) -> Path:
    """写到 reports_dir/YYYY-MM-DD.md；同一天再次运行时覆盖。"""
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{day.isoformat()}.md"
    path.write_text(render_report(results, day), encoding="utf-8")
    return path
