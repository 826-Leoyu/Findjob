import re
import sys
from pathlib import Path

import yaml

from .paths import MASTER_RESUME

DATE_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def load_master(path: Path = MASTER_RESUME) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def bullet_index(master: dict) -> dict[str, str]:
    """id -> 原文。定制简历的追溯检查以此为准。"""
    index = {h["id"]: h["text"] for h in master.get("highlights", [])}
    for entry in master.get("experience", []) + master.get("projects", []):
        for b in entry.get("bullets", []):
            index[b["id"]] = b["text"]
    return index


def validate(master: dict) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()

    def check_id(item: dict, where: str) -> None:
        item_id = item.get("id")
        if not item_id:
            errors.append(f"{where}: 缺少 id")
        elif item_id in seen:
            errors.append(f"{where}: id 重复 {item_id!r}")
        else:
            seen.add(item_id)

    def check_dates(item: dict, where: str) -> None:
        for key in ("start", "end"):
            value = item.get(key)
            if value is None:
                continue
            if not (str(value) == "present" and key == "end") and not DATE_RE.match(str(value)):
                errors.append(f"{where}: {key} 格式应为 YYYY-MM，实际 {value!r}")

    for key in ("name", "email"):
        if not master.get("meta", {}).get(key):
            errors.append(f"meta: 缺少 {key}")

    for i, h in enumerate(master.get("highlights", [])):
        check_id(h, f"highlights[{i}]")
        if not h.get("text"):
            errors.append(f"highlights[{i}]: 缺少 text")

    for section in ("education", "experience", "projects"):
        for i, entry in enumerate(master.get(section, [])):
            where = f"{section}[{i}]"
            check_id(entry, where)
            check_dates(entry, where)
            for j, b in enumerate(entry.get("bullets", [])):
                check_id(b, f"{where}.bullets[{j}]")
                if not b.get("text"):
                    errors.append(f"{where}.bullets[{j}]: 缺少 text")

    return errors


def check_master(path: Path = MASTER_RESUME) -> None:
    master = load_master(path)
    errors = validate(master)
    if errors:
        print("\n".join(errors))
        sys.exit(1)
    print(f"母版校验通过：{len(bullet_index(master))} 条可引用的条目")
