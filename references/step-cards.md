# Step Card：执行卡、冻结与逐步证据

Step Card（执行卡）把已确认意图翻译成**可逐步执行、可逐步验收**的原子步骤。它回答的是“具体怎么做、每步留下什么证据、本步禁止哪些捷径”，不替代 [意图清单](requirements-note.md) 回答“为什么做、交付什么、按什么标准算完成”。

> 本文件的 YAML 是**人读示例**。`scripts/workflow_state.py` 只依赖 Python 标准库，不解析 YAML；机器登记时使用同字段的 UTF-8 JSON（例如 `steps.json`），由人或工具从 YAML 转写。`[推断/扩展]` 字段命名对齐 Bocchiid `plan.json` 的 `action.kind` / `evidence.must_include`，并增加 lab-report 需要的 `modality`、`forbidden_shortcuts`、`screenshot_required`。

## 1. 与意图 MD 的关系

| 文档 | 回答 | 确认/冻结 |
| --- | --- | --- |
| 意图 MD | 要做什么、来源与理由、交付物、完成标准、内容/样式 | 用户明确确认当前版本；确认前不实施 |
| Step Card | 按什么步骤做、每步什么模态、必截点、`must_include`、`forbidden_shortcuts`、失败处理 | 卡内容经用户确认后 `frozen: true`，脚本登记 `freeze_plan` |
| Evidence Binder | 哪些真实证据文件对应哪一步、哪些 `must_include` 已逐项核对 | 全部步骤完成后 `bind_evidence`，才允许写作出口 |

- 执行卡从**已确认的意图**派生。改卡若改变任务范围、评分要求或交付物，先回到意图 MD 重新确认，不能只改卡。
- 改卡若只是执行细节（例如更好的截图位置、补充一条 `forbidden_shortcuts`），也要**重新冻结**并说明差异；不得静默换做法。
- 意图 MD 里的“复用已有环境/免做步”必须在冻结卡中显式标为 `skipped` 并写理由，不能靠模型记忆省略。脚本当前不单独解析 `skipped` 字段，仍要求该步提交能证明复用/免做依据的证据；只写“已做过”不算证据。

## 2. 字段

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| `version` | 建议 | 卡格式版本，当前示例为 `"1.0"` |
| `frozen` | 是（机器登记时） | `false` 为草案；用户确认卡内容后改 `true` 再登记冻结 |
| `steps[]` | 是 | 非空步骤数组；每项是一个可验收原子动作组 |
| `id` | 是 | 卡内唯一，如 `S1`；改名会使已完成记录失配，需重新冻结 |
| `source` | 是 | 对应指导书/报告的具体章节或条目，便于追溯 |
| `goal` | 是 | 本步要完成的可判断目标 |
| `modality` | 是 | `gui` / `cli` / `mixed` / `manual`，按指导书主证据选择 |
| `tool` | 建议 | 指导书点名的具体工具/界面，如 `Postman`、`Wireshark`、`MiniEdit`；不得用同类 CLI 替代 |
| `objects` | 建议 | 本步必须出现的对象清单：拓扑节点、主机名、文件、接口或设备名；来自材料地图或指导书原文 |
| `action` | 是 | 学生视角的实际动作序列；不写“用脚本代做” |
| `screenshot_required` | 是 | 布尔值；`true` 表示本步必须有可读证据图，不能合并跳过 |
| `must_include` | `screenshot_required` 时必填 | 证据中必须可辨认的字段；逐项验收，不是泛泛“有图” |
| `forbidden_shortcuts` | 是 | 本步具体禁令，从 [禁止捷径目录](forbidden-shortcuts.md) 取模式后实例化；非空短语列表 |
| `verify` | 是 | 完成后如何判断本步真的成立 |
| `on_fail` | 是 | 失败后的有界处理，如 `retry_once → ask_user`、`replan_capture_filter` |
| `evidence_ids` | 否 | 与该步关联的证据编号，便于 Evidence Binder 和报告图号对应 |

机器登记还会检查：步骤 `id` 唯一、`modality` 合法、`screenshot_required` 为布尔、`must_include` 无重复、`forbidden_shortcuts` 非空；`gui` 步骤的 `must_include` 应写清界面/字段，不能只写“成功”。`tool` 若填写须为非空字符串；`objects` 若填写须为非空字符串数组。**脚本强制契约**：填写 `tool` 时，`must_include` 至少一项包含该工具名（如“Postman 请求与响应面板”）；填写 `objects` 时，每个对象都须出现在至少一项 `must_include` 中。缺失则 `freeze_plan` 拒绝冻结，并列出缺项。旧卡没有 `tool`/`objects` 仍可冻结。

`must_include` 写法与 `tool`/`objects` 对齐：
- 有 `tool` 时，至少一项写明该工具窗口/界面（如“Postman 请求与响应面板”），不能只写“请求成功”。
- 有 `objects` 时，逐项或成组写进 `must_include`（如“c0、s1、s2、s3、h1–h6 可见”）；不能只写“拓扑正确”。
- 指导书的附步骤/addon 要么单独成卡，要么在意图中显式写明本次不做；卡里不能静默省略。`[来源:lab8-iter]`
- 卡片不要求报告加红框/箭头。标注默认关闭（opt-in）；用户明确要求时才在证据展示副本上加，且不得遮挡 `must_include` 字段。软件自带的红虚线路由/选中高亮不算报告标注。`[来源:lab8-iter]`

## 3. 冻结流程

1. **起草**：按已确认意图写 `steps`（人读 YAML + 机器 JSON 同字段），此时 `frozen: false`。
2. **给用户看**：与意图确认或执行方案一起展示；用户确认卡内容和步骤边界。
3. **标记并冻结**：把卡改为 `frozen: true`，调用 `freeze_plan`，请求中带卡路径和真实确认引用 `message_ref`。脚本校验卡结构，并记录卡摘要与当前意图摘要。
4. **执行**：一次做一步；每步后观察结果，调用 `complete_step`，提交真实证据路径和逐项 `must_include` 结果。
5. **封存**：全部步骤完成后调用 `bind_evidence`。脚本核对所有步骤、证据文件和摘要，生成 `evidence_binder`。
6. **提交出口**：`execution_required` 为 true 时，`submit_draft` 要求冻结卡、全部步骤完成、证据绑定通过。这个门来自 `task_type` 或确认前的显式设置，不默认打开。纯写作、纯审查和未声明类型不走这道门。登记过执行卡时，即使门是关的，已登记的步骤仍须做完并绑定。

卡与意图摘要绑定：意图 MD 变化会使旧卡失效并要求重新确认与冻结，不能沿用旧步骤记录。**改卡/重冻结**：修改卡文件后再次调用 `freeze_plan`，必须提供 `reason`；脚本清除旧的步骤完成记录和证据绑定，要求重新执行受影响步骤。发现更优解、指导书歧义或环境变化时，先改卡再继续，不先做后补。

**证据重采**：如果证据文件在完成步骤后被替换或删除，`status` 会发现摘要不符/文件缺失，使相应步骤和证据绑定失效；重新采集后重新 `complete_step`。不要手改状态 JSON 绕过。

## 4. 脚本闸门（摘要）

| 动作 | 前置 | 拒绝条件 |
| --- | --- | --- |
| `freeze_plan` | 意图已确认，phase=`produce` | 卡未标 `frozen: true`；缺 `message_ref`；步骤结构非法；`tool`/`objects` 未被 `must_include` 点名覆盖；重冻结缺 `reason`；意图已变化 |
| `complete_step` | 已冻结执行卡，phase=`produce` | 执行卡未冻结；步骤不存在或已完成；证据文件缺失/为空；`screenshot_required` 步骤无图片证据；`must_include` 未逐项标 `pass` |
| `bind_evidence` | 所有步骤已完成 | 仍有未完成步骤；证据缺失/摘要不符 |
| `submit_draft` | 登记过执行卡时 | 未冻结；步骤未全完成；证据绑定缺失或与当前卡/步骤不符 |

脚本只检查文件存在、摘要和结构化结果，不能判断截图内容是否真的可读、操作是否真的发生；这些仍由执行者和独立审查负责。

## 5. 最小 JSON

机器只读 JSON。字段以上表为准，按当次指导书填，不照抄工具名。

```json
{"version":"1.0","frozen":true,"steps":[{"id":"S1","source":"指导书对应节","goal":"本步可观察结果","modality":"gui","tool":"指导书点名的工具","objects":["对象甲"],"action":"在该工具里完成指导书这一步","screenshot_required":true,"must_include":["指导书点名的工具 窗口","对象甲"],"forbidden_shortcuts":["用另一工具的文本输出冒充该窗口"],"verify":"窗口里能读到对象甲","on_fail":"retry_once","evidence_ids":["E1"]}]}
```
