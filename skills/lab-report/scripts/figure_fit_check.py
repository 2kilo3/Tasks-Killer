#!/usr/bin/env python3
"""Estimate whether embedded pictures stay readable after page layout (DOCX).

For every picture in the document body the script compares the display width
against the width actually available in that picture's container (body text
column, including columns and gutter, or table cell minus cell padding), and
estimates the on-page height of one line of text from the source pixels.

A picture wider than its container is an error (exit code 1). Text estimated
below the readability threshold is reported as WARN only.

The font estimate needs one assumption: --glyph-px, the pixel height of one
line of text in the source screenshot. The default 20 px is only a rough
desktop-screenshot guess and is not a measurement; pass the value observed in
the screenshots actually used. The result depends on the capture zoom, so
re-check it when the screenshots change.

This reads package XML and layout properties only. It does not render pages;
confirm every page at 100 % zoom in the exported PDF before delivery. Pictures
in headers, footers and footnotes are not inspected.
"""
import argparse
import json
from pathlib import Path
import sys

from docx import Document
from docx.oxml.ns import qn

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
WP = 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'

EMU_PER_MM = 36000
TWIPS_PER_MM = 1440 / 25.4
# OOXML omits cell margins when they are the format default (108 twips). That
# is a cell-padding default, not a page-size guess.
DEFAULT_CELL_MARGIN_TWIPS = 108

# Adjustable estimate, not a measured value: a typical line of text in a
# desktop screenshot is roughly 20 px high. Real captures differ with UI font
# size, display scaling and terminal zoom, so pass --glyph-px per document.
DEFAULT_GLYPH_PX = 20.0

# Adjustable threshold for the estimated on-page height of one text line.
DEFAULT_MIN_FONT_MM = 2.0

# Difference below this is treated as rounding noise, not an overflow.
WIDTH_TOLERANCE_MM = 0.5


def _mm_from_emu(value):
    return value / EMU_PER_MM


def _mm_from_twips(value):
    return value / TWIPS_PER_MM


def _attr_int(element, name, default=None):
    if element is None:
        return default
    key = qn(name) if ':' in name else name
    raw = element.get(key)
    if raw is None:
        return default
    try:
        return int(float(raw))
    except ValueError:
        return default


def _width_spec_mm(spec, reference_mm):
    """Convert a w:tblW/w:tcW element to millimetres, or None when auto."""
    if spec is None:
        return None
    kind = spec.get(qn('w:type')) or 'dxa'
    if kind == 'auto' or kind == 'nil':
        return None
    value = _attr_int(spec, 'w:w')
    if value is None:
        return None
    if kind == 'pct':
        return reference_mm * value / 5000.0
    return _mm_from_twips(value)


def _cell_margins_mm(tc, table):
    """Left/right cell padding in millimetres, with Word's default fallback."""
    left = right = None
    tc_pr = tc.find(qn('w:tcPr'))
    if tc_pr is not None:
        mar = tc_pr.find(qn('w:tcMar'))
        if mar is not None:
            left = _attr_int(mar.find(qn('w:left')), 'w:w')
            right = _attr_int(mar.find(qn('w:right')), 'w:w')
            if left is None:
                left = _attr_int(mar.find(qn('w:start')), 'w:w')
            if right is None:
                right = _attr_int(mar.find(qn('w:end')), 'w:w')
    if left is None or right is None:
        tbl_pr = table.find(qn('w:tblPr'))
        tbl_mar = tbl_pr.find(qn('w:tblCellMar')) if tbl_pr is not None else None
        if tbl_mar is not None:
            if left is None:
                left = _attr_int(tbl_mar.find(qn('w:left')), 'w:w')
                if left is None:
                    left = _attr_int(tbl_mar.find(qn('w:start')), 'w:w')
            if right is None:
                right = _attr_int(tbl_mar.find(qn('w:right')), 'w:w')
                if right is None:
                    right = _attr_int(tbl_mar.find(qn('w:end')), 'w:w')
    if left is None:
        left = DEFAULT_CELL_MARGIN_TWIPS
    if right is None:
        right = DEFAULT_CELL_MARGIN_TWIPS
    return _mm_from_twips(left), _mm_from_twips(right)


def _grid_span(tc):
    tc_pr = tc.find(qn('w:tcPr'))
    span = _attr_int(tc_pr.find(qn('w:gridSpan')) if tc_pr is not None else None, 'w:val')
    return span or 1


def _cell_grid_width_mm(tc, table):
    """Width of the cell's grid columns, used when w:tcW is absent."""
    row = tc.getparent()
    if row is None:
        return None
    index = 0
    for cell in row.findall(qn('w:tc')):
        if cell is tc:
            break
        index += _grid_span(cell)
    span = _grid_span(tc)
    grid = table.find(qn('w:tblGrid'))
    if grid is None:
        return None
    widths = [w for w in (_attr_int(col, 'w:w') for col in grid.findall(qn('w:gridCol'))) if w]
    if not widths:
        return None
    covered = widths[index:index + span]
    if not covered:
        return None
    return _mm_from_twips(sum(covered))


def _table_width_mm(table, text_width_mm):
    tbl_pr = table.find(qn('w:tblPr'))
    spec = tbl_pr.find(qn('w:tblW')) if tbl_pr is not None else None
    return _width_spec_mm(spec, text_width_mm) or text_width_mm


def _cell_container_mm(tc, text_width_mm):
    table = tc.getparent().getparent() if tc.getparent() is not None else None
    if table is None:
        return text_width_mm, 'text_width'
    reference = _table_width_mm(table, text_width_mm)
    tc_pr = tc.find(qn('w:tcPr'))
    spec = tc_pr.find(qn('w:tcW')) if tc_pr is not None else None
    width = _width_spec_mm(spec, reference)
    source = 'tcW'
    if width is None:
        width = _cell_grid_width_mm(tc, table)
        source = 'tblGrid'
    if width is None:
        width = reference
        source = 'table_width'
    left, right = _cell_margins_mm(tc, table)
    return max(width - left - right, 0.0), source


def _cell_ancestor(element):
    node = element.getparent()
    while node is not None:
        if node.tag == qn('w:tc'):
            return node
        node = node.getparent()
    return None


def _top_level_block(element, body):
    node = element
    while node is not None and node.getparent() is not body:
        node = node.getparent()
    return node


def _block_section_index(body):
    """Map each top-level body block's index to its section index."""
    mapping = {}
    section = 0
    for index, child in enumerate(body.iterchildren()):
        if child.tag == qn('w:sectPr'):
            continue
        mapping[index] = section
        if child.tag == qn('w:p'):
            p_pr = child.find(qn('w:pPr'))
            if p_pr is not None and p_pr.find(qn('w:sectPr')) is not None:
                section += 1
    return mapping


def _section_layouts(document):
    """Read each section's real page size. A missing size or margin is a gap.

    This never substitutes a paper size. Callers must report the gap.
    """
    layouts = []
    for index, section in enumerate(document.sections):
        missing = []
        if not section.page_width:
            missing.append('page width')
        if section.left_margin is None:
            missing.append('left margin')
        if section.right_margin is None:
            missing.append('right margin')
        gutter = _mm_from_emu(section.gutter) if section.gutter else 0.0
        columns = 1
        space_mm = 0.0
        cols = section._sectPr.find(qn('w:cols')) if section._sectPr is not None else None
        if cols is not None:
            columns = max(_attr_int(cols, 'w:num', 1), 1)
            space_mm = _mm_from_twips(_attr_int(cols, 'w:space', 720))
        gap = None
        page_width = left = right = text_width = None
        if missing:
            gap = 'section ' + str(index) + ' is missing ' + ', '.join(missing) + '; page size was not assumed'
        else:
            page_width = _mm_from_emu(section.page_width)
            left = _mm_from_emu(section.left_margin)
            right = _mm_from_emu(section.right_margin)
            text_width = page_width - left - right - gutter
            if columns > 1 and text_width > 0:
                text_width = (text_width - space_mm * (columns - 1)) / columns
        layouts.append({
            'page_width_mm': None if page_width is None else round(page_width, 1),
            'left_margin_mm': None if left is None else round(left, 1),
            'right_margin_mm': None if right is None else round(right, 1),
            'gutter_mm': round(gutter, 1),
            'columns': columns,
            'text_width_mm': None if text_width is None else round(max(text_width, 0.0), 1),
            'gap': gap,
        })
    return layouts


def _iter_pictures(body):
    """Yield (drawing, placement, width_emu, height_emu, relationship_id)."""
    for drawing in body.iter(qn('w:drawing')):
        inline = drawing.find(qn('wp:inline'))
        anchor = drawing.find(qn('wp:anchor'))
        holder = inline if inline is not None else anchor
        if holder is None:
            continue
        extent = holder.find(qn('wp:extent'))
        blip = drawing.find('.//' + qn('a:blip'))
        rel_id = blip.get(qn('r:embed')) if blip is not None else None
        yield (
            drawing,
            'inline' if inline is not None else 'floating',
            _attr_int(extent, 'cx'),
            _attr_int(extent, 'cy'),
            rel_id,
        )


def _vml_picture_count(body):
    return sum(1 for _ in body.iter(qn('w:pict')))


def _pixel_size(document, rel_id):
    if not rel_id:
        return None, None
    part = document.part.related_parts.get(rel_id)
    if part is None:
        return None, None
    try:
        image = part.image
        return int(image.px_width), int(image.px_height)
    except Exception:  # unreadable or unsupported picture format
        return None, None


def inspect_document(source, glyph_px=DEFAULT_GLYPH_PX, min_font_mm=DEFAULT_MIN_FONT_MM):
    """Inspect a DOCX path and return the fit report as a dictionary."""
    document = Document(str(source))
    body = document.element.body
    layouts = _section_layouts(document)
    section_by_index = _block_section_index(body)
    block_positions = {id(child): index for index, child in enumerate(body.iterchildren())}
    images = []
    overwide = 0
    small_text = 0
    gaps = [layout['gap'] for layout in layouts if layout.get('gap')]

    for number, (drawing, placement, cx, cy, rel_id) in enumerate(_iter_pictures(body), start=1):
        block = _top_level_block(drawing, body)
        try:
            section_index = section_by_index[block_positions[id(block)]]
        except KeyError:
            section_index = len(layouts) - 1 if layouts else 0
        layout = layouts[section_index] if layouts else {'text_width_mm': None, 'gap': 'no section layout'}
        cell = _cell_ancestor(drawing)
        container_mm = None
        if layout.get('gap') or layout.get('text_width_mm') is None:
            container_source = 'unavailable'
            container = 'body'
        elif cell is not None:
            container_mm, container_source = _cell_container_mm(cell, layout['text_width_mm'])
            container = 'table_cell'
        else:
            container_mm, container_source = layout['text_width_mm'], 'section'
            container = 'body'

        width_mm = _mm_from_emu(cx) if cx else 0.0
        height_mm = _mm_from_emu(cy) if cy else 0.0
        px_width, px_height = _pixel_size(document, rel_id)
        part = document.part.related_parts.get(rel_id) if rel_id else None

        warnings = []
        status = 'ok'
        if layout.get('gap') or container_mm is None:
            status = 'page_gap'
            warnings.append(layout.get('gap') or 'container width unknown')
        if placement != 'inline':
            warnings.append('floating_placement_width_approximate')
        if not cx:
            warnings.append('display_width_missing')
            if status == 'ok':
                status = 'unknown'
        if container_mm is not None and width_mm > container_mm + WIDTH_TOLERANCE_MM:
            status = 'overwide'
            overwide += 1
            warnings.append('width_exceeds_container')
        if part is None:
            status = 'unknown' if status == 'ok' else status
            warnings.append('image_part_missing')
        elif px_width is None:
            status = 'unknown' if status == 'ok' else status
            warnings.append('pixel_size_unknown')

        font_mm = None
        if px_width and width_mm > 0:
            font_mm = glyph_px * width_mm / px_width
            if font_mm < min_font_mm:
                if status == 'ok':
                    status = 'small_text'
                small_text += 1
                warnings.append('font_height_below_threshold')

        images.append({
            'index': number,
            'part': str(part.partname) if part is not None else None,
            'placement': placement,
            'container': container,
            'container_width_mm': None if container_mm is None else round(container_mm, 1),
            'container_width_source': container_source,
            'display_width_mm': round(width_mm, 1),
            'display_height_mm': round(height_mm, 1),
            'px_width': px_width,
            'px_height': px_height,
            'pixels_per_mm': round(px_width / width_mm, 1) if px_width and width_mm > 0 else None,
            'glyph_height_mm': round(font_mm, 2) if font_mm is not None else None,
            'status': status,
            'warnings': warnings,
        })

    vml_skipped = _vml_picture_count(body)
    return {
        'ok': overwide == 0 and not gaps,
        'gaps': gaps,
        'glyph_px': glyph_px,
        'min_font_mm': min_font_mm,
        'sections': layouts,
        'images': images,
        'overwide': overwide,
        'small_text': small_text,
        'vml_pictures_skipped': vml_skipped,
    }


def format_summary(report):
    lines = []
    for gap in report.get('gaps') or []:
        lines.append('GAP ' + gap)
    for section in report['sections']:
        if section.get('gap'):
            continue
        line = ('页宽 {page_width_mm} mm，左右边距 {left_margin_mm}/{right_margin_mm} mm，'
                '正文可用宽 {text_width_mm} mm').format(**section)
        if section['columns'] > 1:
            line += '（{} 栏）'.format(section['columns'])
        lines.append(line)
    for image in report['images']:
        width = 'unknown' if image['container_width_mm'] is None else image['container_width_mm']
        line = '#{index} {container} 显示 {display_width_mm}/{width} mm'.format(width=width, **image)
        if image['px_width']:
            line += ' | 原图 {px_width}x{px_height} px'.format(**image)
        if image['glyph_height_mm'] is not None:
            line += ' | 估算字高 {} mm'.format(image['glyph_height_mm'])
        if image['status'] == 'overwide':
            line += '  OVERWIDE 超出容器约 {} mm'.format(
                round(image['display_width_mm'] - image['container_width_mm'], 1))
        elif image['status'] == 'small_text':
            line += '  WARN 字高低于 {} mm'.format(report['min_font_mm'])
        elif image['status'] == 'page_gap':
            line += '  GAP 缺少页面尺寸，未假定纸张'
        elif image['status'] == 'unknown':
            line += '  WARN 无法估算（' + ','.join(image['warnings']) + '）'
        lines.append(line)
    lines.append('共 {} 张图：超宽 {} 张，字高低于阈值 {} 张，页面尺寸缺口 {}'.format(
        len(report['images']), report['overwide'], report['small_text'], len(report.get('gaps') or [])))
    if report['vml_pictures_skipped']:
        lines.append('另有 {} 张旧式 VML 图片未检查'.format(report['vml_pictures_skipped']))
    return '\n'.join(lines)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='DOCX file to inspect')
    parser.add_argument('--glyph-px', type=float, default=DEFAULT_GLYPH_PX,
                        help='Typical pixel height of one text line in the source screenshots '
                             '(adjustable estimate; measure it on the current captures; default 20)')
    parser.add_argument('--min-font-mm', type=float, default=DEFAULT_MIN_FONT_MM,
                        help='Minimum estimated on-page text height in mm (default 2.0)')
    parser.add_argument('--json', action='store_true', help='Print the full report as JSON instead of the summary')
    args = parser.parse_args(argv)
    try:
        report = inspect_document(args.source, glyph_px=args.glyph_px, min_font_mm=args.min_font_mm)
    except Exception as error:  # missing file, bad package, unsupported image
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(format_summary(report))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
