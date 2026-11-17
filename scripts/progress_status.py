#!/usr/bin/env python3
"""Check task-local progress/STATUS.md against the state phase.

workflow_state.py rewrites this file on every successful action. This command
only checks the contract: heading, stage line, and the done/remaining/blockers
sections. It does not invent extra notes.
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
        text = (args.state.parent / 'progress' / 'STATUS.md').read_text(encoding='utf-8')
        problems = workflow.progress_status_ok(text, state['phase'])
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        return 2
    if problems:
        print(json.dumps({'ok': False, 'problems': problems}, ensure_ascii=False))
        return 1
    print(json.dumps({'ok': True, 'stage': state['phase']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
