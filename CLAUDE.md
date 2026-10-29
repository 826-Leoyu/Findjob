# FindJob

个人半自动求职助手。完整规格见 `SPEC.md`，修改行为前先读它。

## 硬约束

- **不编造**：定制简历 / 求职信只能改写措辞、调整顺序、选择条目。每条 bullet 必须追溯到 `resume/master.yaml` 中的某个 id；没有依据的数字标为待填，交给用户。
- **不自动提交投递**：最后一步永远由用户点击。
- **个人数据不进 git**：`resume/`（除模板外）、`data/`、`output/`、`answers.yaml` 已在 `.gitignore` 中。

## 命令

- `python3 -m findjob init-db` — 创建 / 升级 SQLite（`data/findjob.db`）
- `python3 -m findjob check-master` — 校验母版结构与 id 唯一性
- `python3 -m findjob check-profiles` — 校验 `profiles/*.yaml` 搜索配置（字段见 SPEC §3）
- `python3 -m findjob screen [--rescreen] [--profile NAME]` — 粗筛待筛选职位（排除词 + 粗分）并写回库里，生成日报 `output/reports/YYYY-MM-DD.md`；改了配置后用 `--rescreen` 重新筛选全部 new / skipped 职位
- `python3 -m findjob render [data.yaml] [-o out.pdf] [--png]` — 用 `templates/resume.typ` 渲染简历（需要 `typst`；`--png` 输出逐页预览，便于和原版对比）

修改 `resume/master.yaml` 后必须运行 `check-master`；修改 `profiles/` 后运行 `check-profiles`。

## Agent skills

### Issue tracker

Issues 存放在 GitHub Issues（`826-Leoyu/Findjob`），用 `gh` 操作。See `docs/agents/issue-tracker.md`.

### Triage labels

使用默认的五个标签：needs-triage / needs-info / ready-for-agent / ready-for-human / wontfix。See `docs/agents/triage-labels.md`.

### Domain docs

Single-context：根目录 `GLOSSARY.md` + `docs/adr/`（按需创建）。See `docs/agents/domain.md`.
