"""Job Bank（jobbank.gc.ca）抓取：只用标准库。

Job Bank 的行为（2026-10 实测）：
- 只传 locationstring 会被忽略；要先查城市 id，作为 locationparam 传入（默认半径 50 km）。
- 列表页的职位名会被改写为职业分类名，原始职位名只在详情页里。
- 按省份搜索用 fprov=<省份代码>，结果只含该省职位。
"""

import html
import json
import math
import re
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from . import store

BASE = "https://www.jobbank.gc.ca"

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) FindJob/0.1 (personal job search)"
REQUEST_INTERVAL_S = 1.0
PAGE_SIZE = 25
REMOTE_FILTER = "15141"  # fskl=15141：Workplace = Remote
SEARCH_RADIUS_KM = 50  # Job Bank 按城市搜索的默认半径
MERGE_KM = 40          # 离已有搜索中心不到这个距离的城市不再单独搜索
PROVINCES = {
    "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba", "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador", "NS": "Nova Scotia", "NT": "Northwest Territories",
    "NU": "Nunavut", "ON": "Ontario", "PE": "Prince Edward Island", "QC": "Quebec",
    "SK": "Saskatchewan", "YT": "Yukon",
}

ARTICLE_RE = re.compile(r'<article id="article-(\d+)".*?</article>', re.S)


@dataclass
class Listing:
    source_id: str
    url: str
    title: str
    company: str
    location: str
    posted_at: str | None
    origin: str | None     # 原始来源：Job Bank / Talent.com / indeed.com ...
    workplace: str | None  # Remote / Hybrid / On site；未标注为 None


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _first(pattern: str, s: str) -> str | None:
    m = re.search(pattern, s, re.S)
    return _text(m.group(1)) if m else None


def _location(raw: str) -> str:
    """'Toronto (ON)' / 'Victoria, BC' -> 'Toronto, ON'"""
    raw = raw.replace("Location", "", 1).strip()
    m = re.match(r"^(.*?)\s*\((\w{2})\)$", raw)
    return f"{m.group(1)}, {m.group(2)}" if m else raw


def _date(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


def parse_search(page: str) -> list[Listing]:
    listings = []
    for m in ARTICLE_RE.finditer(page):
        art = m.group(0)
        source_id = m.group(1)
        listings.append(Listing(
            source_id=source_id,
            url=f"{BASE}/jobsearch/jobposting/{source_id}",
            title=_first(r'<span class="noctitle">(.*?)</span>', art) or "",
            company=_first(r'<li class="business">(.*?)</li>', art) or "",
            location=_location(_first(r'<li class="location">(.*?)</li>', art) or ""),
            posted_at=_date(_first(r'<li class="date">(.*?)</li>', art)),
            origin=_first(r'<span class="job-source[^"]*"><span class="wb-inv">(.*?)</span>', art),
            workplace=_first(r'<span class="telework">(.*?)</span>', art),
        ))
    return listings


@dataclass
class Posting:
    original_title: str
    description: str
    workplace: str | None
    external_url: str | None  # 转载职位的原站申请链接


def parse_posting(page: str) -> Posting:
    original = _first(r'<span class="orig-title-label">.*?</span>(.*?)</span>', page)
    # 转载职位的 description 是转义过的 HTML，要先还原再去标签；
    # Job Bank 会把它截断在约 5000 字符处，可能留下半个标签。
    raw_desc = re.search(r'<span class="hidden" property="description">(.*?)</span>\s*<', page, re.S)
    description = _text(re.sub(r"<[^>]*$", "", html.unescape(raw_desc.group(1)))) if raw_desc else ""
    workplace = re.search(r"Workplace information: ([A-Za-z ]+?)\.", description)
    link = re.search(r'<a id="externalJobLink"[^>]*href="([^"]+)"', page)
    return Posting(
        original_title=original or _first(r'<span property="title">(.*?)</span>', page) or "",
        description=description,
        workplace=workplace.group(1) if workplace else None,
        external_url=html.unescape(link.group(1)) if link else None,
    )


def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def split_locations(locations: list[str]) -> tuple[list[str], list[str]]:
    """把配置地点分成（省份代码，城市）；已被列出的省份覆盖的城市去掉。"""
    by_name = {name.lower(): code for code, name in PROVINCES.items()}
    provinces, cities = [], []
    for loc in locations:
        key = loc.strip()
        code = key.upper() if key.upper() in PROVINCES else by_name.get(key.lower())
        (provinces if code else cities).append(code or loc)
    cities = [c for c in cities if c.rpartition(",")[2].strip().upper() not in provinces]
    return provinces, cities


def plan_searches(locations: list[str], coords: dict[str, tuple[float, float]]) -> list[str]:
    """按配置顺序挑出搜索中心；查不到坐标的地点跳过。"""
    centers: list[str] = []
    for loc in locations:
        if loc not in coords:
            continue
        if all(_distance_km(coords[loc], coords[c]) >= MERGE_KM for c in centers):
            centers.append(loc)
    return centers


_last_request = 0.0


def fetch(url: str) -> tuple[str, str]:
    """GET，返回（重定向后的 URL，正文）。两次请求至少间隔 REQUEST_INTERVAL_S。"""
    global _last_request
    wait = _last_request + REQUEST_INTERVAL_S - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    try:
        with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=30) as resp:
            return resp.geturl(), resp.read().decode("utf-8", errors="replace")
    finally:
        _last_request = time.monotonic()


def lookup_city(location: str) -> tuple[str, float, float] | None:
    """'Windsor, ON' -> (city_id, 纬度, 经度)；查不到返回 None。"""
    city, _, prov = (part.strip() for part in location.partition(","))
    query = urlencode({"q": city, "fq": "NOT postalcode_cnt:0", "wt": "json", "rows": 25})
    _, body = fetch(f"{BASE}/core/ta-cityprovsuggest_en/select?{query}")
    for doc in json.loads(body)["response"]["docs"]:
        if doc.get("doctype") == "C" and doc["name"].lower() == city.lower() \
                and (not prov or doc["province_cd"] == prov.upper()):
            return doc["city_id"], doc["latitude"], doc["longitude"]
    return None


def _with_page(url: str, page: int) -> str:
    parts = urlsplit(url)
    path = parts.path.split(";")[0]  # 去掉 jsessionid
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "page"] + [("page", str(page))]
    return urlunsplit((parts.scheme, parts.netloc, path, urlencode(query), ""))


def _search_urls(profile: dict, provinces: list[str], city_ids: dict[str, str], centers: list[str]) -> list[str]:
    urls = []
    for keyword in profile["keywords"]:
        for prov in provinces:
            urls.append(f"{BASE}/jobsearch/jobsearch?" + urlencode(
                {"searchstring": keyword, "fprov": prov, "sort": "D", "fage": 30}))
        for center in centers:
            urls.append(f"{BASE}/jobsearch/jobsearch?" + urlencode(
                {"searchstring": keyword, "locationparam": city_ids[center], "sort": "D", "fage": 30}))
        if profile["remote"]:
            urls.append(f"{BASE}/jobsearch/jobsearch?" + urlencode(
                {"searchstring": keyword, "fskl": REMOTE_FILTER, "sort": "D", "fage": 30}))
    return urls


def scrape(profile: dict, conn: sqlite3.Connection, max_pages: int = 4, log=print) -> Counter:
    """按配置搜索 Job Bank，新职位抓详情后入库。返回 new / seen / dup / error 计数。"""
    stats: Counter = Counter()
    provinces, cities = split_locations(profile["locations"])
    city_ids, coords = {}, {}
    for loc in cities:
        found = lookup_city(loc)
        if found is None:
            log(f"  找不到城市：{loc}，跳过")
            continue
        city_ids[loc], *latlon = found
        coords[loc] = tuple(latlon)
    centers = plan_searches(cities, coords)
    log(f"  搜索范围：{', '.join(provinces + centers)}" + ("，另加远程" if profile["remote"] else ""))

    known = store.known_source_ids(conn, "jobbank")
    searched: set[str] = set()
    for url in _search_urls(profile, provinces, city_ids, centers):
        final_url, page = fetch(url)
        # Job Bank 会把不同关键词改写成同一个查询，按改写后的 URL 去重
        canonical = _with_page(final_url, 1)
        if canonical in searched:
            continue
        searched.add(canonical)
        for page_no in range(1, max_pages + 1):
            if page_no > 1:
                _, page = fetch(_with_page(final_url, page_no))
            listings = parse_search(page)
            fresh = [l for l in listings if l.source_id not in known]
            for listing in fresh:
                known.add(listing.source_id)
                try:
                    posting = parse_posting(fetch(listing.url)[1])
                except OSError as e:
                    log(f"  详情页失败 {listing.url}: {e}")
                    stats["error"] += 1
                    continue
                workplace = posting.workplace or listing.workplace
                stats[store.save(conn, store.Job(
                    source="jobbank", source_id=listing.source_id, url=listing.url,
                    title=posting.original_title or listing.title, company=listing.company,
                    location=listing.location,
                    remote=None if workplace is None else workplace == "Remote",
                    posted_at=listing.posted_at, description=posting.description,
                ), profile["name"])] += 1
            if not fresh or len(listings) < PAGE_SIZE:
                break
    log(f"  查询 {len(searched)} 个，新增 {stats['new']}，跨来源重复 {stats['dup']}，失败 {stats['error']}")
    return stats
