#!/usr/bin/env python3
"""Flag heading runs that depart from a declared font and size baseline.

The baseline comes from the current template or the confirmed style. This
script does not treat any typeface or point size as a universal rule. A missing
baseline is an error. XML-only: it does not render pages or resolve every
inherited style.
"""
import argparse
import json
from pathlib import Path
import sys
import zipfile
import xml.etree.ElementTree as ET

WORD = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
W = '{' + WORD + '}'
DOCUMENT_PART = 'word/document.xml'


def is_heading(paragraph):
    properties = paragraph.find(W + 'pPr')
    if properties is None:
        return False
    style = properties.find(W + 'pStyle')
    if style is not None:
        value = style.get(W + 'val') or ''
        if 'heading' in value.lower() or '标题' in value:
            return True
    return properties.find(W + 'outlineLvl') is not None


def run_violations(run, baseline_half_points, baseline_east_asia, baseline_ascii):
    results = []
    properties = run.find(W + 'rPr')
    if properties is None:
        return results
    fonts = properties.find(W + 'rFonts')
    if fonts is not None:
        east_asia = fonts.get(W + 'eastAsia')
        if east_asia and east_asia != baseline_east_asia:
            results.append({'kind': 'font_departure', 'axis': 'eastAsia', 'value': east_asia,
                            'baseline': baseline_east_asia})
        ascii_font = fonts.get(W + 'ascii')
        if baseline_ascii and ascii_font and ascii_font != baseline_ascii:
            results.append({'kind': 'font_departure', 'axis': 'ascii', 'value': ascii_font,
                            'baseline': baseline_ascii})
    size = properties.find(W + 'sz')
    if size is not None:
        try:
            half_points = int(size.get(W + 'val'))
        except (TypeError, ValueError):
            half_points = None
        if half_points is not None and half_points > baseline_half_points:
            results.append({'kind': 'size_upgrade', 'value': half_points / 2,
                            'baseline_pt': baseline_half_points / 2})
    return results


def find_violations(xml_bytes, baseline_half_points, baseline_east_asia, baseline_ascii=None):
    """Return one record per heading run that leaves the declared baseline."""
    if not isinstance(baseline_east_asia, str) or not baseline_east_asia.strip():
        raise ValueError('baseline east-asia font is required; do not assume a typeface')
    if not isinstance(baseline_half_points, int) or baseline_half_points <= 0:
        raise ValueError('baseline size in half-points is required; do not assume a body size')
    root = ET.fromstring(xml_bytes)
    records = []
    for paragraph in root.iter(W + 'p'):
        if not is_heading(paragraph):
            continue
        text = ''.join(node.text or '' for node in paragraph.iter(W + 't'))
        for run in paragraph.iter(W + 'r'):
            for violation in run_violations(run, baseline_half_points, baseline_east_asia, baseline_ascii):
                records.append(dict(paragraph=text, **violation))
    return records


def read_document_xml(source):
    if zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as archive:
            return archive.read(DOCUMENT_PART)
    return source.read_bytes()


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='DOCX file or raw word/document.xml')
    parser.add_argument('--baseline-font', required=True,
                        help='Declared east-asia body/heading font from the template or confirmed style')
    parser.add_argument('--baseline-ascii',
                        help='Declared latin font. Checked only when a heading run sets w:ascii')
    parser.add_argument('--baseline-pt', required=True, type=float,
                        help='Declared body size in points from the template or confirmed style')
    parser.add_argument('--json', action='store_true', help='Print the violation list as JSON')
    args = parser.parse_args(argv)
    if args.baseline_pt <= 0:
        print(json.dumps({'ok': False, 'error': 'baseline-pt must be positive'}, ensure_ascii=False))
        return 2
    try:
        records = find_violations(read_document_xml(args.source), round(args.baseline_pt * 2),
                                  args.baseline_font, args.baseline_ascii)
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError, ValueError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        return 2
    if args.json:
        print(json.dumps({'ok': not records, 'baseline_font': args.baseline_font,
                          'baseline_pt': args.baseline_pt, 'violations': records}, ensure_ascii=False))
    else:
        for record in records:
            print('VIOLATION ' + record['paragraph'] + ': ' + record['kind'] + '=' + str(record['value']))
    return 1 if records else 0


if __name__ == '__main__':
    sys.exit(main())
