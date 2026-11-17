# tasks-killer

**目标写清，对照真实产物做完，只在两处请人看。**

这是一个解题用的 Agent Skill。`tasks-killer` 负责目标、材料、实现、验收和返工。报告、模板、版式和终页核验在旁边的 `lab-report`。外部工具各自留在 `skills/` 里，用到才加载。

## 两道人审

1. 让目标变成一份可追溯的文档，独立 AI 先对照材料审过，再请人确认。
2. 最终结果同样先由独立 AI 对照目标和真实产物审过，再请人看验证材料。

沉默不是确认。进度、中间稿、把一条纠正收成检查，都不叫人。卡住（缺权限、材料冲突、环境不可用）或你点名要看某一步时才停。

## 并发

目标确认之后，互不依赖的段可以并行。需要独占同一台机器或同一把资源的段用 `scripts/resource_lock.py` 排队。每一段自己做完并核对产物。只有编排者写 `state.json` 和 `progress/STATUS.md`。

## 越用越不容易重犯

一条纠正如果下次还能判对错，就写成 `constraints/` 里的规则，`scripts/constraint_lint.py` 会让下一次直接失败。还写不成检查的，才在任务目录留 `NOTES.md`。不要把教训堆进 `SKILL.md`。

不要写未经约定的 Markdown。约定过的是目标文档、`progress/STATUS.md`、`MATERIALS_MAP.md`，以及任务点名的文件。

## 形式检查

`formal/TasksKiller.tla` 描述阶段、两道人审、独占锁和恢复。`formal/TasksKiller.lean` 证明锁的新旧、证据绑定和门条件。没有 TLC 或 Lean 时，`python -B formal/check_model.py` 枚举同一套规则。命令见 [formal/README.md](formal/README.md)。

## 开始使用

```sh
git clone https://github.com/2kilo3/lab-report.git
```

整目录复制，保留 `SKILL.md`、`references/`、`scripts/`、`skills/`、`formal/`、`constraints/`、`docs/`、`tests/` 的相对位置。

| 宿主 | 位置 |
| --- | --- |
| Codex | `.agents/skills/tasks-killer/` |
| Claude Code | `.claude/skills/tasks-killer/` |
| Cursor | `.cursor/skills/tasks-killer/` 或 `.agents/skills/tasks-killer/` |
| 通用 Agent | 能读到 `SKILL.md` 的目录 |

```text
请使用 tasks-killer。先读 course-input/ 里的任务和材料，写出目标文档。
格式以任务书为准；没写就先问。原模板不要改。
```

成稿若是报告或论文，技能会再加载 `skills/lab-report`。需要某个外部工具时，它按 `skills/*/SKILL.md` 的说明去匹配，不在主流程里写死工具。机器名、账号和地址放在任务外面的配置里。

## 仓库

```text
SKILL.md                         tasks-killer 入口
skills/lab-report/               报告适配：写作、模板、版式、图和终页
skills/<tool>/                   按需加载的工具技能
scripts/workflow_state.py        状态、人审门、段锁、产物门
scripts/resource_lock.py         独占资源的租约锁
scripts/constraint_lint.py       由纠正变成的规则
scripts/progress_status.py       检查 progress/STATUS.md
scripts/markdown_gate.py         拒绝未经约定的 Markdown
formal/                          TLA+、Lean、可执行枚举
constraints/                     已落地的规则
references/                      目标、执行卡、禁令、编排
tests/                           合成契约测试
```

状态和进度文件写在任务目录，不写进技能目录。

## 验证

```sh
python -B -m unittest discover -s tests -p "test_*.py"
python -B formal/check_model.py
python -B scripts/constraint_lint.py
```

`tests/scenarios.md` 仍是行为设计，不是已跑过的课程实验。本仓库的单测不证明真实实验、真实页面或某家宿主已经端到端跑通。记录见 [docs/validation.md](docs/validation.md)。

## 变更

| 版本 | 变化 |
| --- | --- |
| 3.0.0 | 主技能改为 tasks-killer。lab-report 只保留写作、模板、版式和终页。去掉私有经验库。人审默认只留目标文档和最终结果，之前各有一次独立 AI 审查。段可以并行，独占资源继续用锁。补上 TLA+、Lean 和可执行状态枚举。纠正先进 `constraints/`。交付格式、执行证据门、字体字号和纸张都不再写死。 |
| 2.4.1 | 随包附带工具技能；本机配置留在包外 |
| 2.4.0 | 资源锁、插图估算、DONE 产物门 |
| 2.3.0 | 材料地图、执行卡门、审查白名单的机器检查 |
| 2.2.0 | 材料地图、分段编排、具名工具与对象清单 |
| 2.1.0 | 当时的私有经验层。3.0.0 已删除 |
| 2.0 | 可溯源意图、真实证据、状态恢复 |
