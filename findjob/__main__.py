import argparse
from pathlib import Path

from . import db
from .paths import DB_PATH, MASTER_RESUME, OUTPUT_DIR


def _select_profiles(name: str | None, parser: argparse.ArgumentParser) -> list[dict]:
    """不指定时取全部启用的配置；指定 name 时只取这一份（停用的也算），不存在则报错退出。"""
    from .profiles import load_profiles

    profiles = load_profiles(enabled_only=name is None)
    if name:
        profiles = [p for p in profiles if p["name"] == name]
        if not profiles:
            parser.error(f"没有名为 {name!r} 的配置")
    return profiles


def main() -> None:
    parser = argparse.ArgumentParser(prog="findjob")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db", help="创建或升级 SQLite 数据库")
    sub.add_parser("check-master", help="校验 resume/master.yaml 的结构与 id 唯一性")
    sub.add_parser("check-profiles", help="校验 profiles/*.yaml 搜索配置")
    scrape = sub.add_parser("scrape", help="按启用的搜索配置抓取职位并入库")
    scrape.add_argument("--profile", help="只运行这一份配置（按 name）")
    scrape.add_argument("--max-pages", type=int, default=4, help="每个查询最多翻几页")
    screen = sub.add_parser("screen", help="粗筛待筛选的职位并生成当天日报")
    screen.add_argument("--rescreen", action="store_true", help="重新筛选全部 new 与 skipped 职位")
    screen.add_argument("--profile", help="只处理这一份配置的职位（按 name）")
    render = sub.add_parser("render", help="把简历 YAML 渲染成 PDF")
    render.add_argument("data", nargs="?", type=Path, default=MASTER_RESUME)
    render.add_argument("-o", "--out", type=Path, default=OUTPUT_DIR / "master.pdf")
    render.add_argument("--png", action="store_true", help="同时输出每页的 PNG 预览")
    args = parser.parse_args()

    if args.cmd == "init-db":
        db.init_db()
        print(f"数据库已就绪：{DB_PATH}")
    elif args.cmd == "check-master":
        from .master import check_master

        check_master()
    elif args.cmd == "check-profiles":
        from .profiles import check_profiles

        check_profiles()
    elif args.cmd == "scrape":
        from . import jobbank

        profiles = _select_profiles(args.profile, parser)
        db.init_db()
        with db.connect() as conn:
            for profile in profiles:
                print(f"[jobbank] {profile['name']}")
                jobbank.scrape(profile, conn, max_pages=args.max_pages)
    elif args.cmd == "screen":
        import datetime

        from .report import write_report
        from .screen import screen_pending

        profiles = _select_profiles(args.profile, parser)
        db.init_db()
        with db.connect() as conn:
            run = screen_pending(conn, {p["name"]: p for p in profiles},
                                 rescreen=args.rescreen, only_profile=args.profile)
        path = write_report(run.results, OUTPUT_DIR / "reports", datetime.date.today())
        kept = sum(v.keep for _, v in run.results)
        print(f"保留 {kept}，过滤 {len(run.results) - kept}，日报：{path}")
        for name, n in sorted(run.unmatched.items(), key=lambda kv: str(kv[0])):
            print(f"  跳过 {n} 条：配置 {name!r} 已停用或不存在")
    elif args.cmd == "render":
        from .render import render_resume

        render_resume(args.data, args.out)
        if args.png:
            render_resume(args.data, args.out.with_name(args.out.stem + "-{p}.png"), fmt="png")
        print(f"已生成：{args.out}")


if __name__ == "__main__":
    main()
