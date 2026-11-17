---
name: tasks-killer
description: 把任务收成可验收的目标，对照真实材料与产物做完并复核。默认只在目标文档和最终结果两处请人确认；此前由独立 AI 审查。适用于要证据、可回退、可并行的解题与制作。
metadata:
  version: "3.0.0"
---

# tasks-killer

顺序固定：目标与验收 → 材料与缺口 → 实现 → 对照真实产物验收。没过的只返工没过的部分。一个编排者写 `state.json` 和 `progress/STATUS.md`。

不要写未经约定的 Markdown。

## 允许的 Markdown

- 目标文档（任务要求的那一份意图）
- `progress/STATUS.md`：当前阶段、已完成、剩余、阻塞。每一步都更新
- `MATERIALS_MAP.md`
- 任务或用户点名的文件：先 `allow_markdown`，记下路径和理由
- `NOTES.md`：只有这条纠正还写不成检查时，先 `allow_notes`

不写辩解、额外说明或过程日记。教训不追加到本文件。能检查的纠正用 `scripts/constraint_lint.py add` 写成 `constraints/` 里的规则，下一次跑不过就不能跳。

## 两道人审

1. 目标文档。独立 AI 先对照材料和目标审查。`record_goal_review` 为 pass 才进入 `awaiting_confirmation`。rework 继续改，不叫人。只有 `conflict` 或真实阻塞才停。
2. 最终结果。`record_review` 为 pass 才进入 `awaiting_final`。人看验证产物：模型检查、证明、截图、真实输出。不看每一稿。

沉默不是确认。`confirm` 和 `confirm_final` 要宿主核对过的 `message_ref`。进度、中间稿、把纠正收成检查，都不叫人。中途只在缺权限、材料冲突、环境不可用，或用户点名要看某一步时停。

## 阶段

`intake` → `goal_review` → `awaiting_confirmation` → `produce` → `review` → `awaiting_final` → `done`。`blocked` 与 `failed` 记下原因再恢复。动作表见 [状态机](references/state-machine.md)。同一规则的 TLA+ 模型和 Lean 证明见 [formal/README.md](formal/README.md)。

执行证据门不默认打开。`init` 读 `task_type`：`execution` / `lab` / `mixed` 打开；`writing` / `review` / `analysis` / `unspecified` 关闭。例外在确认前用 `set_execution_required` 写明理由。

交付格式从当前任务和已确认意图读取。没写就问一次。

## 材料与实现

- 地图：[materials-map.md](references/materials-map.md)。硬要求带 `map_id`。
- 目标文档：[requirements-note.md](references/requirements-note.md)。
- 目标冻结后，互不依赖的段并行。独占资源用 [resource_lock.py](scripts/resource_lock.py) 串行，并 `register_segments` / `claim_segment` / `verify_segment`。锁只在心跳超租约或进程不在时算失效；`break-stale` 要有理由，然后 `recover_segment`。
- 每一段自己实现并对照真实产物验收。
- 执行卡、禁令、取证：[step-cards.md](references/step-cards.md)、[forbidden-shortcuts.md](references/forbidden-shortcuts.md)、[execution.md](references/execution.md)、[human-ops.md](references/human-ops.md)、[shared-resources.md](references/shared-resources.md)、[orchestration.md](references/orchestration.md)。

### 工具

任务需要外部工具时，读 `skills/*/SKILL.md` 的 description，加载匹配的技能。机器名、账号、地址只放任务外部配置。训练夹具不是真实结果。

成稿是报告、论文或带模板的文档时，加载 [lab-report](skills/lab-report/SKILL.md)。模板、写作、版式、图和终页核验在那个技能里。

## 命令

```sh
python -B scripts/workflow_state.py --state task/state.json --request task/action.json
python -B scripts/progress_status.py --state task/state.json
python -B scripts/markdown_gate.py --state task/state.json
python -B scripts/constraint_lint.py
python -B formal/check_model.py
```

状态放任务目录。脚本不跑实验，退出码也不是用户同意。恢复先 `status`，再看真实文件。
