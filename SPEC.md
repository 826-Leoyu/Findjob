# FindJob 规格说明

个人使用的半自动求职助手：自动找职位、打分、按 JD 定制简历；最终投递由用户本人点击提交。

## 1. 范围

- 使用者：仅本人（PGWP 持有人）。无账号系统、无服务器。
- 市场：加拿大，含"可在加拿大远程"的职位。
- 级别：默认 New Grad / Entry / Junior；排除 Senior 及要求 5 年以上经验的职位。
- 职位方向：不固定，由搜索配置决定（见 §3）。

## 2. 技术栈

- Python（抓取、去重、粗筛、追踪）
- SQLite（职位与投递状态）
- Typst（简历 / 求职信 PDF 渲染）
- Claude Code skills（精评、简历定制、求职信）——走订阅，不调用付费 API
- git 管理代码；个人数据进 `.gitignore`，永不推送到公开仓库

## 3. 搜索配置

- 用户用自然语言描述需求 → 转成 `profiles/<name>.yaml`。
- 字段：关键词、排除词、地点、远程是否接受、经验上限、启用开关、ATS 公司列表（可选）。
- 地点可以写城市（按 50 km 半径搜索）或省份（搜全省；职位在该省即视为符合）。
- 定时任务运行所有启用的配置。

## 4. 数据来源（按实现顺序）

1. **Job Bank**（加拿大政府）——审查并复用旧项目 AutoApply 的 `server/jobbank.py`。
2. **ATS 公司页面**——Greenhouse / Lever / Ashby 公开 JSON 接口，公司列表由用户指定。
3. **python-jobspy**——Indeed / Glassdoor / LinkedIn 公开列表；不登录、低频。

跨来源去重（公司 + 标题 + 地点规范化）。

## 5. 打分

1. **粗筛（Python，定时，无 LLM）**：按关键词/排除词/地点/经验年限过滤，按关键词重合度给粗分。
   - 要求 security clearance → 直接过滤。
   - 要求 PR / citizen → 保留但标红。
2. **精评（Claude，在 `/jobs` 内）**：对粗分 Top N（默认 15）对比 JD 与母版，输出 0–100 匹配分、匹配点、缺口、风险提示。

## 6. 简历

- **母版** `resume/master.yaml`：从 `resume/Yulin_Yu__Resume.pdf` 提取，含全部事实与"项目池"，不限长度。
- **定制版**：保留 3 页结构——前两页（Highlights、经历、技能等）针对 JD 定制，第 3 页为项目附录。
- **硬约束**：只允许改写措辞、调整顺序、选择条目、突出 JD 关键词；不得编造技能、经历或数字。每条输出 bullet 必须可追溯到母版条目（记录来源 id），并做自动一致性检查。无依据的数字标为待填。
- **样式**：Typst 模板复刻原 PDF（蓝色标题、日期右对齐、分节结构）。
- **项目素材**：读取用户 GitHub 项目（MyPersonalUseApp、ShadoVox-RM、ai-developer-practice-arena、AutoApply、FindJob 本身），产出候选 bullet 清单，由用户挑选后才进入母版。

## 7. 求职信与常见问题

- 求职信仅在职位要求或允许上传时生成。
- `answers.yaml`（用户填写一次）：期望薪资、最早入职时间、是否愿意搬家、链接（LinkedIn / GitHub）、工作许可等。
  - 当前是否有加拿大工作许可：Yes（PGWP，记录到期日）
  - 将来是否需要担保：No
- "Why this company" 等开放题按职位单独起草，用户审核。

## 8. 流程与追踪

- **每日定时**（cron 或 Windows 任务计划 → `wsl`）：抓取 → 去重 → 入库 → 粗筛 → 生成日报（Markdown / HTML）。
- **`/jobs` skill**：列出新职位与精评结果 → 用户选择 → 生成定制简历（及求职信）→ 给出投递链接 → 用户手动投递 → 更新状态。
- 状态：新发现 → 已评分 → 已定制 → 已投递 → 面试 / 拒绝。

## 9. 第二版（不在 MVP 内）

- Playwright 表单预填（先 Greenhouse、Lever），最终由用户点提交。
- 推送通知（邮件 / Telegram）。

## 10. 实现步骤

1. 项目骨架：目录结构、`.gitignore`、Python 环境、SQLite schema。
2. 母版：PDF → `resume/master.yaml`，用户校对。
3. Typst 模板：从母版渲染出与原 PDF 一致的简历（视觉回归对比）。
4. 搜索配置格式 + 第一份配置。
5. Job Bank 抓取（审查复用 AutoApply）+ 去重入库。
6. Python 粗筛 + 日报生成。
7. `/jobs` skill：精评、定制简历、追溯检查、求职信、状态更新。
8. `answers.yaml` 模板。
9. 定时任务配置。
10. ATS（Greenhouse / Lever / Ashby）抓取。
11. python-jobspy 抓取。
12. GitHub 项目素材挖掘 → 候选 bullet 清单。
