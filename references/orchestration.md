# 编排

切的是上下文，不是权限，也不是共享环境。一个编排者写 `state.json` 和 `progress/STATUS.md`。

## 分段

| 段 | 输入 | 输出 | 不拿 |
| --- | --- | --- | --- |
| 读材料 | 一份材料 | `map_id` 与短引文 | 未确认目标、草稿 |
| 目标 | 地图、用户要求 | 目标文档 | 执行细节、旧通过结论 |
| 目标审查 | 材料、地图、目标草稿 | goal review 收据 | 制作方的“没问题” |
| 实现 | 已确认目标、冻结卡、本段资源 | 证据与 `verify_segment` | 其他段的自评 |
| 成稿审查 | 下面的白名单 | REVIEW 表与收据 | 历史通过、整段聊天 |
| 返工 | REVIEW 里点名的行和证据 | 受影响部分 | 无关章节的旧稿 |

## 并发

独占与离线的分法见 [shared-resources.md](shared-resources.md)。目标确认后才能 `register_segments`。

- 独占段：`resource_lock.py` acquire，`claim_segment` 带 `lock_path`，做完 verify，再 release。
- 无独占资源的段：不持锁，可以同时 `running`。
- 同一资源上不能有两段 `running`。
- 心跳看锁里的 `heartbeat_at` 或 `heartbeats/<段>.json` 的 `pid`、`host`、`heartbeat_at`。
- dead：进程不在，或心跳超过租约。先 `break-stale`（必须有理由），再 `recover_segment`。
- stuck：进程还在、心跳新鲜，但过了预计时间仍无新产物。停掉该段，从最后一份真实产物继续。
- 不根据会话自述判断死活。

## 审查白名单

| 允许 | 说明 |
| --- | --- |
| 原始任务、模板、评分、指导、范例 | 按文件回读 |
| `MATERIALS_MAP.md` | 索引，不是全文 |
| 已确认目标 | 当前版本 |
| 冻结执行卡和逐步证据 | 需要这道门时 |
| 当前成稿和最终渲染 | 这一版生成的 |
| 证据原件 | 与对象、轮次对应 |

不允许制作方的“已完成”总结、旧审查收据、整段聊天、无关私人材料。

`review_gate` 只证明文件在。审查者仍要自己看白名单里的原文。

REVIEW 表每一行：问题 | `map_id` / 目标条 / 图或段落 | 严重度 | 应改动作 | 是否阻断。对不上依据的标待核实。

报告的页面和样式另见 [lab-report 清单](../skills/lab-report/references/review-checklist.md)。

## 文件

| 文件 | 放什么 |
| --- | --- |
| `progress/STATUS.md` | 阶段、已完成、剩余、阻塞 |
| `state.json` | 阶段、确认、锁和证据绑定 |
| 目标文档 | 要做什么和怎样算完成 |
| `MATERIALS_MAP.md` | 材料索引 |
| `NOTES.md` | 仅 `allow_notes` 之后，还不能写成检查的一条 |
| `constraints/` | 已经能检查的纠正 |

`progress/STATUS.md` 不是授权，也不是验收结论。
