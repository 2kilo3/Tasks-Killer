#!/usr/bin/env python3
"""Enumerate the tasks-killer state machine and check the same invariants as the TLA+ model.

The TLA+ module formal/TasksKiller.tla is the spec. This checker is the executable
layer that runs without TLC: two segments, one exclusive resource, the two human
gates, AI review before each gate, lock recovery, and an execution-evidence flag.
"""
from collections import deque

PHASES = (
    'intake', 'goal_review', 'awaiting_confirmation', 'produce', 'review',
    'awaiting_final', 'done', 'blocked',
)
SEGMENT = ('pending', 'running', 'verified', 'rework')


def initial(execution_required):
    return {
        'phase': 'intake',
        'goal_ai': False,
        'goal_human': False,
        'final_ai': False,
        'final_human': False,
        'seg': {'S0': 'pending', 'S1': 'pending'},
        'lock': None,
        'execution_required': execution_required,
        'blocked_from': None,
    }


def clone(state, **updates):
    copied = {
        'phase': state['phase'],
        'goal_ai': state['goal_ai'],
        'goal_human': state['goal_human'],
        'final_ai': state['final_ai'],
        'final_human': state['final_human'],
        'seg': dict(state['seg']),
        'lock': state['lock'],
        'execution_required': state['execution_required'],
        'blocked_from': state['blocked_from'],
    }
    copied.update(updates)
    if 'seg' in updates:
        copied['seg'] = dict(updates['seg'])
    return copied


def key(state):
    return (
        state['phase'], state['goal_ai'], state['goal_human'], state['final_ai'], state['final_human'],
        state['seg']['S0'], state['seg']['S1'], state['lock'], state['execution_required'], state['blocked_from'],
    )


def evidence_bound(state):
    return state['seg']['S0'] == 'verified' and state['seg']['S1'] == 'verified'


def successors(state, resources):
    found = []

    def add(item):
        found.append(item)

    phase = state['phase']
    if phase == 'intake':
        add(clone(state, phase='goal_review', goal_ai=False, goal_human=False))
    if phase == 'goal_review':
        add(clone(state, phase='awaiting_confirmation', goal_ai=True))
        add(clone(state, phase='goal_review', goal_ai=False))
        add(clone(state, phase='blocked', blocked_from='goal_review'))
    if phase == 'awaiting_confirmation' and state['goal_ai']:
        add(clone(state, phase='produce', goal_human=True))
    if phase == 'produce' and state['goal_human']:
        for sid in ('S0', 'S1'):
            if state['seg'][sid] not in {'pending', 'rework'}:
                continue
            resource = resources[sid]
            if resource and state['lock'] not in {None, sid}:
                continue
            if resource and any(other != sid and resources[other] == resource and state['seg'][other] == 'running'
                                for other in ('S0', 'S1')):
                continue
            seg = dict(state['seg'])
            seg[sid] = 'running'
            add(clone(state, seg=seg, lock=sid if resource else state['lock'], final_ai=False, final_human=False))
        for sid in ('S0', 'S1'):
            if state['seg'][sid] != 'running':
                continue
            seg = dict(state['seg'])
            seg[sid] = 'verified'
            lock = None if state['lock'] == sid else state['lock']
            add(clone(state, seg=seg, lock=lock))
        for sid in ('S0', 'S1'):
            if state['seg'][sid] not in {'running', 'verified'}:
                continue
            seg = dict(state['seg'])
            seg[sid] = 'rework'
            lock = None if state['lock'] == sid else state['lock']
            add(clone(state, seg=seg, lock=lock, final_ai=False, final_human=False))
        for sid in ('S0', 'S1'):
            if state['seg'][sid] != 'running':
                continue
            seg = dict(state['seg'])
            seg[sid] = 'rework'
            lock = None if state['lock'] == sid else state['lock']
            add(clone(state, seg=seg, lock=lock))
        if evidence_bound(state) or not state['execution_required']:
            if all(state['seg'][sid] == 'verified' for sid in ('S0', 'S1')) or not state['execution_required']:
                if state['execution_required'] and not evidence_bound(state):
                    pass
                elif any(state['seg'][sid] == 'running' for sid in ('S0', 'S1')):
                    pass
                else:
                    add(clone(state, phase='review'))
    if phase == 'review' and state['goal_human']:
        add(clone(state, phase='awaiting_final', final_ai=True))
        add(clone(state, phase='produce', final_ai=False, final_human=False))
        add(clone(state, phase='blocked', blocked_from='review'))
    if phase == 'awaiting_final' and state['final_ai']:
        add(clone(state, final_human=True))
        if state['final_human'] and (evidence_bound(state) or not state['execution_required']):
            add(clone(state, phase='done'))
    if phase == 'done':
        add(clone(state, phase='review', final_ai=False, final_human=False))
    if phase not in {'blocked', 'done'}:
        add(clone(state, phase='blocked', blocked_from=phase))
    if phase == 'blocked' and state['blocked_from']:
        add(clone(state, phase=state['blocked_from'], blocked_from=None))
    return found


def invariants(state, resources):
    errors = []
    if state['goal_human'] and not state['goal_ai']:
        errors.append('human goal gate without AI goal pass')
    if state['final_human'] and not state['final_ai']:
        errors.append('human final gate without AI final pass')
    if state['phase'] in {'produce', 'review', 'awaiting_final', 'done'} and not state['goal_human']:
        errors.append('work started before the goal was confirmed')
    if state['phase'] == 'awaiting_confirmation' and not state['goal_ai']:
        errors.append('goal human gate opened before AI pass')
    if state['phase'] == 'awaiting_final' and not state['final_ai']:
        errors.append('final human gate opened before AI pass')
    if state['phase'] == 'done':
        if not (state['goal_human'] and state['final_human'] and state['goal_ai'] and state['final_ai']):
            errors.append('done without both human gates and both AI passes')
        if state['execution_required'] and not evidence_bound(state):
            errors.append('execution task done without evidence')
    running = [sid for sid in ('S0', 'S1') if state['seg'][sid] == 'running' and resources[sid]]
    if len(running) > 1 and len({resources[sid] for sid in running}) < len(running):
        errors.append('two segments running on one exclusive resource')
    if state['lock'] is not None:
        holder = state['lock']
        if state['seg'][holder] != 'running' or not resources[holder]:
            errors.append('lock held by a segment that is not running it')
    for sid in ('S0', 'S1'):
        if state['seg'][sid] == 'running' and resources[sid] and state['lock'] != sid:
            errors.append('running exclusive segment lost its lock')
    return errors


def explore(resources, execution_required):
    start = initial(execution_required)
    seen = {key(start): start}
    order = deque([start])
    failures = []
    while order:
        state = order.popleft()
        for nxt in successors(state, resources):
            ident = key(nxt)
            problems = invariants(nxt, resources)
            if problems:
                failures.append({'state': ident, 'problems': problems})
            if ident not in seen:
                seen[ident] = nxt
                order.append(nxt)
    return list(seen.values()), failures


def check():
    report = {'ok': True, 'configurations': []}
    configs = [
        ({'S0': 'R', 'S1': 'R'}, True),
        ({'S0': 'R', 'S1': None}, False),
    ]
    for resources, execution_required in configs:
        states, failures = explore(resources, execution_required)
        both_running = any(item['seg']['S0'] == 'running' and item['seg']['S1'] == 'running' for item in states)
        done = any(item['phase'] == 'done' for item in states)
        exclusive = resources['S0'] and resources['S0'] == resources['S1']
        problems = list(failures)
        if not done:
            problems.append({'state': None, 'problems': ['done was not reachable']})
        if exclusive and both_running:
            problems.append({'state': None, 'problems': ['exclusive segments ran together']})
        if not exclusive and not both_running:
            problems.append({'state': None, 'problems': ['independent segment never ran beside the locked one']})
        report['configurations'].append({
            'resources': resources,
            'execution_required': execution_required,
            'states': len(states),
            'failures': problems,
        })
        if problems:
            report['ok'] = False
    return report


if __name__ == '__main__':
    import json
    import sys
    result = check()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result['ok'] else 1)
