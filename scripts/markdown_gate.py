#!/usr/bin/env python3
"""Refuse unsolicited markdown in a task directory.

Allowed: the goal document, progress/STATUS.md, MATERIALS_MAP.md, NOTES.md only
after allow_notes, and paths recorded with allow_markdown. Exit 0 when the
directory matches that set, 1 when extra markdown is present, 2 on input errors.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys


def load_workflow():
    spec = importlib.util.spec_from_file_location('workflow_state', Path(__file__).with_name('workflow_state.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True, type=Path)
    args = parser.parse_args(argv)
    workflow = load_workflow()
    try:
        state = workflow.read_json(args.state)
        result = workflow.check_markdown(state, args.state.parent.resolve())
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
