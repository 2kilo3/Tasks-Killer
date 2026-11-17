# tasks-killer

State a checkable goal, implement independent segments concurrently, and check the outcome against real artifacts. A separate AI review precedes each of the two human gates: the goal document, and the final result.

高信任的多技能编排：目标写清，对照真实产物做完，能检查的纠正收成规则，只在两处请人看。`tasks-killer` 管目标、材料、实现和验收。`lab-report` 是并列的报告技能，负责模板、写作、版式、图和终页。

版本 3.0.0。状态脚本标明 Python 3.9+ 标准库。本仓库没有 LICENSE 文件，也没有 CI 配置。

## 开始

规范地址是 [2kilo3/Tasks-Killer](https://github.com/2kilo3/Tasks-Killer)。`2kilo3/lab-report` 会跳转到这里。

```sh
git clone https://github.com/2kilo3/Tasks-Killer.git
```

整目录复制，保持 `SKILL.md`、`references/`、`scripts/`、`skills/`、`formal/`、`constraints/`、`docs/`、`tests/` 的相对位置。

| 宿主 | 放置 |
| --- | --- |
| Codex | `.agents/skills/tasks-killer/` |
| Claude Code | `.claude/skills/tasks-killer/` |
| Cursor | `.cursor/skills/tasks-killer/` 或 `.agents/skills/tasks-killer/` |
| 其他 | 宿主能读到 `SKILL.md` 的目录 |

上表是文件该放的位置，不表示已经在该宿主里端到端跑通。

```text
请使用 tasks-killer。先读 course-input/ 里的任务和材料，写出目标文档。
格式以任务书为准；没写就先问。原模板不要改。
```

成稿若是报告或论文，再加载 `skills/lab-report`。外部工具按 `skills/*/SKILL.md` 的 description 匹配，不写进主流程。机器名、账号和地址放在任务外面的配置里。

## 怎么工作

顺序固定：目标与验收 → 材料与缺口 → 实现 → 对照真实产物验收。没过的只返工没过的部分。一个编排者写 `state.json` 和 `progress/STATUS.md`。

1. 目标写成可追溯的文档。独立 AI 对照材料审过，`record_goal_review` 为 pass，才请人确认。
2. 最终结果同样先由独立 AI 对照目标和真实产物审过，`record_review` 为 pass，才请人看验证材料。

沉默不是确认。`confirm` 和 `confirm_final` 要宿主核对过的 `message_ref`。进度、中间稿、把一条纠正收成检查，都不叫人。缺权限、材料冲突、环境不可用，或你点名要看某一步时才停。

目标确认之后，互不依赖的段可以并行。需要独占同一台机器或同一把资源的段用 `scripts/resource_lock.py` 排队。每一段自己做完并核对产物。

一条纠正如果下次还能判对错，就写成 `constraints/` 里的规则，`scripts/constraint_lint.py` 会让下一次直接失败。还写不成检查的，才在任务目录留 `NOTES.md`。教训不追加到 `SKILL.md`。

不要写未经约定的 Markdown。约定过的是目标文档、`progress/STATUS.md`、`MATERIALS_MAP.md`，以及任务点名的文件。

阶段是 `intake` → `goal_review` → `awaiting_confirmation` → `produce` → `review` → `awaiting_final` → `done`。`formal/TasksKiller.tla` 描述阶段、两道人审、独占锁和恢复。`formal/TasksKiller.lean` 证明锁的新旧、证据绑定和门条件。没有 TLC 或 Lean 时，`python -B formal/check_model.py` 枚举同一套规则。见 [formal/README.md](formal/README.md)。

执行证据门不默认打开。`task_type` 为 `execution` / `lab` / `mixed` 时打开；`writing` / `review` / `analysis` / `unspecified` 时关闭。交付格式读当前任务和已确认意图。没写就问一次。

## 仓库

```text
SKILL.md                         tasks-killer 入口
skills/lab-report/               并列的报告技能：写作、模板、版式、图和终页
skills/vmware-lab-pair/          按需加载：探测已在运行的 VMware 客户机
skills/postman-local-lab/        按需加载：本机 Postman CLI；夹具不是真实服务
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

状态和进度写在任务目录，不写进技能目录。3.0.0 起主技能是 tasks-killer。更早的记录在 git 历史和 [docs/validation.md](docs/validation.md)。

## 它不是

- 不是课程实验运行器。`tests/scenarios.md` 仍是行为设计。单测、模型枚举和约束检查不证明真实实验、真实页面或某家宿主已经端到端跑通。
- 模板、学术写作、版式、图和终页在 `skills/lab-report`，由任务需要时加载。
- 不替任务选定交付格式、字体、字号或纸张。
- 训练夹具和脚本退出码不是真实结果，也不是用户同意。

## 检查

```sh
python -B -m unittest discover -s tests -p "test_*.py"
python -B formal/check_model.py
python -B scripts/constraint_lint.py
```

## 许可

本仓库没有 LICENSE 文件。写作指导的第三方许可原文在 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)，不改变用户材料或模板的许可。
