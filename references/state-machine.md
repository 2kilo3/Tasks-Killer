# 状态机

实现：[scripts/workflow_state.py](../scripts/workflow_state.py)。Python 3.9+ 标准库。只检查文件和转换，不跑实验、不叫 Agent、不授权。

```sh
python -B scripts/workflow_state.py --state <任务目录/state.json> --request <请求.json>
```

相对路径以 state 所在目录为基准。成功退出 0，守门失败退出 2。同一任务只有编排者写这个文件。每次成功动作都会重写 `progress/STATUS.md`。

阶段：`intake` → `goal_review` → `awaiting_confirmation` → `produce` → `review` → `awaiting_final` → `done`。`blocked` / `failed` 保存 `resume_phase`。形式模型：[formal/TasksKiller.tla](../formal/TasksKiller.tla)。

## 人审门

- `submit_intention` 进入 `goal_review`，不叫人。
- `record_goal_review`：`pass` 才到 `awaiting_confirmation`；`rework` 留在 `goal_review`；`conflict` 进入 `blocked`。
- `confirm` 只接受 `awaiting_confirmation`，且目标审查已 pass，并要真实 `message_ref`。沉默不是确认。
- `record_review`：`pass` 才到 `awaiting_final`；`rework` 回 `produce`；`conflict` 进入 `blocked`。
- `confirm_final` 要真实 `message_ref`，绑定当前审查收据。
- `finish` 只在 `awaiting_final` 且最终确认仍匹配时，核对交付产物后进入 `done`。

`confirm`、`confirm_final`、`finish` 会拒绝任务目录里未经允许的 Markdown。允许的是目标文档、`progress/STATUS.md`、`MATERIALS_MAP.md`、`allow_notes` 之后的 `NOTES.md`，以及 `allow_markdown` 登记过的路径。

## 动作

- init：`maker`、`sources`。`task_type` 为 `unspecified`（默认）/`writing`/`review`/`analysis` 时 `execution_required` 为 false；`execution`/`lab`/`mixed` 时为 true。请求里的布尔值优先于类型。`require_materials_map` 默认 true。已有状态不能再 init。
- set_execution_required / set_require_materials_map：确认前，带理由。
- register_materials_map：确认前。
- submit_intention：`path`；地图门打开时还要 `map_ids`。进入 `goal_review`。
- record_goal_review：`path`。收据含 `target=goal`、另一身份的 `reviewer`、`context_ref`、`intention_sha256`、`verdict`、`findings`。
- confirm：`message_ref`。进入 `produce`。
- register_segments：`segments` 为 `{id, exclusive_resource, depends_on}` 列表。已有图再登记要 `reason`。有段在跑时拒绝。
- claim_segment：`id`、`owner`。独占段还要 `lock_path`，且 `resource_lock.py` 里这把锁由该 owner 持有、未过期。
- verify_segment：`id`、`owner`、非空 `evidence`。独占段的锁仍须有效。
- rework_segment：`id`、`reason`。
- recover_segment：`id`、`reason`、`stale: true`。独占锁必须已经空着或过期。先用 `resource_lock.py break-stale` 处理过期锁并留下理由。
- freeze_plan / complete_step / bind_evidence：字段与旧执行卡门相同。`tool` 和 `objects` 必须被 `must_include` 点名。
- submit_draft：`paths`，`evidence` 可空。`execution_required` 时必须有冻结卡、全部步骤和证据绑定。登记过的段必须全部 `verified`。进入 `review`。
- review_gate：`review` / `awaiting_final` / `done`。`required` 可追加路径。
- record_review：收据字段与以前相同（`reviewer` 不同于 `maker`、`context_ref`、`basis`、`verdict`、六项 checks）。`requirements`、`writing`、`final_file` 不能是 `not_applicable`。
- confirm_final：`message_ref`。
- finish：`artifacts`。存在、非空、mtime 晚于 `stage_started_at`、路径不重复。
- rollback：`to` 为 `intake` / `produce` / `review`，加 `reason`。回 intake 撤销确认和目标审查。
- pause / resume / set_sources / reassess：与以前相同。来源变化先 `blocked`。
- allow_notes：`reason`。之后才可以有 `NOTES.md`。
- allow_markdown：`path`、`reason`。
- markdown_gate：只检查，不改阶段。
- status：不改阶段。产物变了会先失效再返回。

旧 schema 1 或 2 在第一次读取时去掉经验库字段，升到 schema 3，并在旁边留下 `.schemaN.bak`。已经 `done` 的旧任务保留 legacy 最终确认标记，避免把历史完成记录打回未完成。新任务不会拿到这个标记。缺 `execution_required` 的旧状态按 false 处理。

## 产物与进度

`finish` 的产物门只证明存在、非空、新鲜。不证明内容正确，也不证明用户已经收下。

`progress/STATUS.md` 必须有 `# STATUS`、`- stage: <phase>`、`- updated:`、`## done`、`## remaining`、`## blockers`。检查：

```sh
python -B scripts/progress_status.py --state task/state.json
```

请求可以带 `progress_done`、`progress_remaining`、`progress_blockers` 三个字符串列表，用来替换自动摘要。
