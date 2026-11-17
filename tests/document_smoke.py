#!/usr/bin/env python3
"""Optional synthetic DOCX smoke. Structural checks do not certify page appearance."""
import argparse
import json
from pathlib import Path
import shutil

from docx import Document
from docx.enum.section import WD_SECTION_START
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt


AUTHOR = 'Synthetic Test Author'


def protected(document):
    return [p._p.xml for p in document.paragraphs[:2]] + [document.tables[0]._tbl.xml] + [s._sectPr.xml for s in document.sections]


def build(output):
    output.mkdir(parents=True, exist_ok=True)
    template = output / 'synthetic-template.docx'
    document = Document()
    document.sections[0].page_width, document.sections[0].page_height = Inches(8.5), Inches(11)
    document.styles['Normal'].font.name = 'Arial'
    document.styles['Normal'].font.size = Pt(12)
    title = document.add_paragraph('SYNTHETIC TEMPLATE - FIXED COVER')
    title.runs[0].font.size = Pt(18)
    title.runs[0].bold = True
    document.add_paragraph('Protected author target: ' + AUTHOR)
    table = document.add_table(rows=2, cols=2)
    table.style = 'Table Grid'
    table.cell(0, 0).text, table.cell(0, 1).text = 'FIXED SCORE AREA', 'DO NOT EDIT'
    table.cell(1, 0).text, table.cell(1, 1).text = 'Synthetic criterion', 'Reserved'
    document.add_section(WD_SECTION_START.NEW_PAGE)
    document.add_paragraph('ALLOWED BODY AREA')
    document.add_paragraph('Synthetic observation: only caption alignment is changed in this fixture.')
    document.add_paragraph('Figure 1. Synthetic caption')
    document.core_properties.author = AUTHOR
    document.core_properties.last_modified_by = AUTHOR
    document.save(template)
    baseline = protected(Document(template))
    target = output / 'synthetic-caption.docx'
    shutil.copyfile(template, target)
    current = Document(target)
    caption = next(paragraph for paragraph in current.paragraphs if paragraph.text.startswith('Figure 1.'))
    caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
    current.core_properties.author = AUTHOR
    current.core_properties.last_modified_by = AUTHOR
    current.save(target)
    reopened = Document(target)
    if protected(reopened) != baseline:
        raise SystemExit('Protected cover/table/sections drifted')
    if reopened.core_properties.author != AUTHOR or reopened.core_properties.last_modified_by != AUTHOR:
        raise SystemExit('Author metadata drifted')
    records = [dict(file=target.name, protected_xml_unchanged=True,
                    author=reopened.core_properties.author,
                    last_modified_by=reopened.core_properties.last_modified_by,
                    visual_status='REQUIRES SEPARATE RENDER AND PAGE INSPECTION')]
    (output / 'structural-checks.json').write_text(
        json.dumps({'synthetic': True, 'checks': records}, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')
    return records


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    print(build(parser.parse_args().output.resolve()))
