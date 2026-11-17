---
name: lab-report
description: 在已确认的目标和真实证据上写、改、核报告或论文。保护模板，处理学术写作、版式、图和样式，并在最终页面上重读。交付格式以任务和已确认意图为准。
metadata:
  version: "3.0.0"
---

# lab-report

任务要写或核带模板、版式或页面的文档时才加载。目标、人审和状态归 tasks-killer。这里不新开人审，也不改已确认目标。

交付格式读任务和已确认意图。意图没写格式时问一次，不替任务选定格式。

## 规则

- 写作：[academic-writing.md](references/academic-writing.md)
- 模板、图、元数据：[document-output.md](references/document-output.md)
- 终页和样式清单：[review-checklist.md](references/review-checklist.md)
- 可选编辑路线，都可以降级：[portability.md](references/portability.md)
- 条件化例子：[examples.md](references/examples.md)

原始模板不改。只编辑副本允许区。封面、评分栏、分节按模板保护。字体和字号用这份模板或已确认样式里的值，不用另一份文档的习惯。

## 检查

样式对照声明的基线。缺基线就是错误，脚本不替你假定字型或字号。

```sh
python -B skills/lab-report/scripts/docx_style_check.py 候选.docx --baseline-font 模板字体 --baseline-pt 模板磅值
```

图幅读文档里的页宽和边距。缺了就报缺口，不另选纸张。

```sh
python -B skills/lab-report/scripts/figure_fit_check.py 候选.docx --glyph-px 当次截图字高
```

最终渲染要逐页打开看。XML、结构检查和旧预览不能代替这一眼。作者和最后修改者用本次核实的姓名，保存后再打开核对。
