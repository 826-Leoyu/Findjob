import sys
from pathlib import Path

import yaml

from .paths import PROFILES_DIR

REQUIRED = {
    "name": str,
    "enabled": bool,
    "keywords": list,
    "exclude": list,
    "locations": list,
    "remote": bool,
    "max_experience_years": int,
}
OPTIONAL = {"ats_companies": list}


def load_profile(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def validate(profile: dict, path: Path) -> list[str]:
    errors: list[str] = []
    where = path.name
    for key, kind in REQUIRED.items():
        if key not in profile:
            errors.append(f"{where}: 缺少 {key}")
        elif not isinstance(profile[key], kind) or (kind is int and isinstance(profile[key], bool)):
            errors.append(f"{where}: {key} 应为 {kind.__name__}")
    for key, kind in OPTIONAL.items():
        if key in profile and not isinstance(profile[key], kind):
            errors.append(f"{where}: {key} 应为 {kind.__name__}")
    for key in ("keywords", "exclude", "locations", "ats_companies"):
        items = profile.get(key)
        if isinstance(items, list) and not all(isinstance(x, str) and x.strip() for x in items):
            errors.append(f"{where}: {key} 只能包含非空字符串")
    if isinstance(profile.get("keywords"), list) and not profile["keywords"]:
        errors.append(f"{where}: keywords 不能为空")
    if not profile.get("locations") and not profile.get("remote"):
        errors.append(f"{where}: locations 为空时 remote 必须为 true")
    if profile.get("name") and profile["name"] != path.stem:
        errors.append(f"{where}: name 应与文件名一致（{path.stem}）")
    unknown = set(profile) - set(REQUIRED) - set(OPTIONAL)
    if unknown:
        errors.append(f"{where}: 未知字段 {sorted(unknown)}")
    return errors


def load_profiles(enabled_only: bool = True, directory: Path = PROFILES_DIR) -> list[dict]:
    """读取并校验所有配置；有错误时抛出 ValueError。"""
    profiles, errors = [], []
    for path in sorted(directory.glob("*.yaml")):
        profile = load_profile(path)
        errors += validate(profile, path)
        profiles.append(profile)
    if errors:
        raise ValueError("\n".join(errors))
    return [p for p in profiles if p["enabled"] or not enabled_only]


def check_profiles(directory: Path = PROFILES_DIR) -> None:
    try:
        profiles = load_profiles(enabled_only=False, directory=directory)
    except ValueError as e:
        print(e)
        sys.exit(1)
    for p in profiles:
        state = "启用" if p["enabled"] else "停用"
        print(f"{p['name']}（{state}）：{len(p['keywords'])} 个关键词，{len(p['locations'])} 个地点，远程={p['remote']}")
