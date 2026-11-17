#!/usr/bin/env python3
"""Write the workflow SVG and HTML. A PNG is not generated here."""
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'docs' / 'images'
PAPER, INK, SOFT = '#f5f5f5', '#2d3142', '#4f5d75'
COLORS = {'new': '#2563a6', 'affected': '#bf4520', 'original': '#697386'}


def text(x, y, label, size=16, color=INK, weight=400):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}">{escape(label)}</text>'


def box(x, y, width, height, label, lines, kind, tag=None):
    color = COLORS[kind]
    tag = tag or {'new': '新增', 'affected': '受影响 · 原门槛保留', 'original': '原职责保留'}[kind]
    return (f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="6" fill="{PAPER}" stroke="{color}" stroke-width="2"/>'
            + text(x + 16, y + 26, tag, 13, color)
            + text(x + 16, y + 60, label, 22, INK, 600)
            + ''.join(text(x + 16, y + 88 + 24 * i, line, 15, SOFT) for i, line in enumerate(lines)))


def arrow(path, dashed=False):
    return f'<path d="{path}" fill="none" stroke="{SOFT}" stroke-width="2" marker-end="url(#arrow)"' + (' stroke-dasharray="5 4"' if dashed else '') + '/>'


def save(name, title, desc, height, content, legend_new='新增：经验层'):
    legend = ''.join(f'<rect x="{40 + i * 320}" y="{height - 46}" width="20" height="20" fill="none" stroke="{color}" stroke-width="2"/>'
                     + text(72 + i * 320, height - 30, label, 15, SOFT)
                     for i, (color, label) in enumerate([(COLORS['new'], legend_new), (COLORS['affected'], '受影响：原环节与门槛保留'), (COLORS['original'], '灰框：保持原职责')]))
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 {height}" role="img" aria-labelledby="{name}-title {name}-desc">'
           f'<title id="{name}-title">{escape(title)}</title><desc id="{name}-desc">{escape(desc)}</desc>'
           '<defs><style>text{font-family:"Microsoft YaHei","Noto Sans SC",sans-serif}</style>'
           f'<marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10z" fill="{SOFT}"/></marker></defs>'
           f'<rect width="1200" height="{height}" fill="{PAPER}"/>'
           + text(40, 44, 'tasks-killer / 3.0', 14, SOFT) + text(40, 88, title, 30, INK, 600)
           + content + f'<path d="M40 {height - 64} H1160" stroke="#bfc0c0"/>' + legend + '</svg>')
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / (name + '.svg')).write_text(svg + '\n', encoding='utf-8')
    html = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{escape(title)}</title><style>body{{margin:0;padding:24px;background:{PAPER}}}.diagram-container{{overflow-x:auto}}'
            'svg{display:block;width:100%;min-width:1200px}@media print{svg{min-width:0}}</style><body><div class="diagram-container">'
            + svg + '</div></body></html>\n')
    (ROOT / (name + '.html')).write_text(html, encoding='utf-8')


def build():
    stages = [('01 目标审查', ['AI 对照材料', 'pass 才请人看']),
              ('02 人确认目标', ['message_ref', '沉默不算确认']),
              ('03 分段实现', ['并行离线段', '独占资源加锁']),
              ('04 对照产物', ['段内验收', '缺了就返工']),
              ('05 终审与交付', ['AI 再审结果', '人看验证材料'])]
    flow = arrow('M140 236 V268')
    flow += ''.join(arrow(f'M{x + 200} 342 H{x + 228}') for x in (40, 272, 504, 736))
    flow += arrow('M600 416 V452')
    flow += box(40, 116, 1120, 120, '00 材料与目标', ['MATERIALS_MAP 索引全部已给材料', '目标文档写清要做什么、依据和完成标准'], 'original', '入口')
    for i, (label, lines) in enumerate(stages):
        flow += box(40 + i * 232, 268, 200, 148, label, lines, 'affected')
    flow += box(40, 452, 1120, 120, '一个编排者', ['state.json 与 progress/STATUS.md 只由编排者写', '纠正先进 constraints；未经约定不另写 Markdown'], 'new', '3.0')
    flow += text(40, 620, '形式层：formal/TasksKiller.tla 与 TasksKiller.lean。工具不在时跑 formal/check_model.py。', 16, SOFT)
    save('workflow', 'tasks-killer · 目标、实现、两道人审', '材料与目标之后，AI 先审目标，人确认，然后分段实现并对照产物，最后 AI 与人各看一次最终结果。', 700, flow, '3.0：进度与约束')


if __name__ == '__main__':
    build()
