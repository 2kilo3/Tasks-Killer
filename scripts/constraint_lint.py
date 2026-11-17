#!/usr/bin/env python3
"""Run learned constraints. A correction becomes a rule with a clear error.

Rules live in constraints/*.json. Each rule names repo-relative paths and
either forbids a regex or requires one. Add a rule with `add`; do not grow
SKILL.md to store the lesson. Exit 0 when every rule holds, 1 when a rule
fails, 2 on usage or rule-file errors.
"""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def load_rules(directory):
    rules = []
    paths = sorted(Path(directory).glob('*.json'))
    if not paths:
        raise ValueError('No constraint rules in ' + str(directory))
    for path in paths:
        rule = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(rule, dict) or not rule.get('id') or not rule.get('message'):
            raise ValueError('Rule file needs id and message: ' + path.name)
        if not rule.get('paths'):
            raise ValueError('Rule file needs paths: ' + path.name)
        if not rule.get('forbid_regex') and not rule.get('require_regex'):
            raise ValueError('Rule file needs forbid_regex or require_regex: ' + path.name)
        rule['_file'] = path.name
        rules.append(rule)
    return rules


def check(rules, root):
    failures = []
    for rule in rules:
        compiled_forbid = [re.compile(pattern) for pattern in rule.get('forbid_regex') or []]
        compiled_require = [re.compile(pattern) for pattern in rule.get('require_regex') or []]
        for relative in rule['paths']:
            target = (root / relative).resolve()
            if not target.is_file():
                failures.append({'id': rule['id'], 'path': relative, 'error': 'missing file',
                                 'message': rule['message']})
                continue
            text = target.read_text(encoding='utf-8')
            for pattern in compiled_forbid:
                match = pattern.search(text)
                if match:
                    failures.append({'id': rule['id'], 'path': relative, 'error': 'forbidden: ' + match.group(0),
                                     'message': rule['message']})
            for pattern in compiled_require:
                if not pattern.search(text):
                    failures.append({'id': rule['id'], 'path': relative, 'error': 'required pattern missing: ' + pattern.pattern,
                                     'message': rule['message']})
    return failures


def add_rule(directory, rule_id, paths, forbid, require, message):
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', rule_id):
        raise ValueError('id must be lowercase words separated by hyphens')
    if not message.strip():
        raise ValueError('message is required')
    path_list = [item for item in paths.split(',') if item.strip()]
    if not path_list:
        raise ValueError('at least one path is required')
    forbid_list = [item for item in (forbid or '').split('||') if item]
    require_list = [item for item in (require or '').split('||') if item]
    if not forbid_list and not require_list:
        raise ValueError('provide --forbid-regex or --require-regex')
    for pattern in forbid_list + require_list:
        re.compile(pattern)
    payload = {'id': rule_id, 'paths': path_list, 'message': message.strip()}
    if forbid_list:
        payload['forbid_regex'] = forbid_list
    if require_list:
        payload['require_regex'] = require_list
    destination = Path(directory) / (rule_id + '.json')
    if destination.exists():
        raise ValueError('Rule already exists: ' + destination.name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--rules', type=Path, default=ROOT / 'constraints')
    sub = parser.add_subparsers(dest='command')
    added = sub.add_parser('add', help='Write one new constraint from a correction')
    added.add_argument('--id', required=True)
    added.add_argument('--paths', required=True, help='Comma-separated repo-relative files')
    added.add_argument('--forbid-regex', help='Regexes separated by ||')
    added.add_argument('--require-regex', help='Regexes separated by ||')
    added.add_argument('--message', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'add':
            destination = add_rule(args.rules, args.id, args.paths, args.forbid_regex, args.require_regex, args.message)
            print(json.dumps({'ok': True, 'wrote': str(destination)}, ensure_ascii=False))
            return 0
        failures = check(load_rules(args.rules), args.root)
    except (OSError, ValueError, json.JSONDecodeError, re.error) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        return 2
    if failures:
        print(json.dumps({'ok': False, 'failures': failures}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({'ok': True, 'rules': len(list(Path(args.rules).glob('*.json')))}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
