import os
import shutil
import subprocess
from pathlib import Path

from .paths import ROOT

TEMPLATE = ROOT / "templates" / "resume.typ"
# 原版用 Liberation 字体；本机用等宽度的 Windows Times New Roman / Arial 代替
DEFAULT_FONT_PATH = "/mnt/c/Windows/Fonts"


def render_resume(data: Path, out: Path, fmt: str = "pdf") -> None:
    """把与 master.yaml 同结构的 YAML 渲染成 PDF（或 png 预览，out 中用 {p} 表示页码）。"""
    typst = shutil.which("typst")
    if typst is None:
        raise SystemExit("找不到 typst，请先安装到 PATH")
    data = data.resolve()
    if not data.is_relative_to(ROOT):
        raise SystemExit(f"数据文件必须在项目目录内：{data}")
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        typst, "compile",
        "--root", str(ROOT),
        "--input", f"data=/{data.relative_to(ROOT).as_posix()}",
        "--format", fmt,
    ]
    font_path = os.environ.get("FINDJOB_FONT_PATH", DEFAULT_FONT_PATH)
    if Path(font_path).is_dir():
        cmd += ["--font-path", font_path]
    if fmt == "png":
        cmd += ["--ppi", "80"]
    subprocess.run(cmd + [str(TEMPLATE), str(out)], check=True)
