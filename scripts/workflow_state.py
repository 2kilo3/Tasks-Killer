#!/usr/bin/env python3
"""Task state ledger for tasks-killer (Python 3.9+, standard library only).

Usage: python -B scripts/workflow_state.py --state WORK/state.json --request action.json

The phase names and gate order match formal/TasksKiller.tla. This tool checks
files and transition conditions. It does not run experiments, invoke agents,
grant permission, or certify review quality. A same-permission writer can
tamper with the ledger. Silence is not a confirmation: human gates require an
explicit message_ref supplied by the host after it has seen a real reply.

Requests and results are UTF-8 JSON. Relative paths resolve against the state
file's directory. State stays in the task directory, not the skill install.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile

PHASES = {
    'intake', 'goal_review', 'awaiting_confirmation', 'produce', 'review',
    'awaiting_final', 'done', 'failed', 'blocked',
}
CHECKS = {'requirements', 'evidence', 'writing', 'format', 'render', 'final_file'}
MODALITIES = {'gui', 'cli', 'mixed', 'manual'}
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tif', '.tiff'}
SEGMENT_STATUSES = {'pending', 'running', 'verified', 'rework'}
MEMORY_KEYS = (
    'task_id', 'session_ref', 'invocation_id', 'memory_mode', 'lessons_used',
    'lessons_receipt', 'adoption_generation', 'memory_impact_pending',
    'lessons_history', 'memory_checkpoint',
)
# Unspecified, writing, review, and analysis do not force an execution-evidence
# gate. execution / lab / mixed do, because the task type says evidence of
# doing the work is part of acceptance. An explicit boolean overrides the type.
TASK_EXECUTION = {
    'unspecified': False,
    'writing': False,
    'review': False,
    'analysis': False,
    'execution': True,
    'lab': True,
    'mixed': True,
}
PHASE_REMAINING = {
    'intake': 'Read materials, register the map, and draft the goal document',
    'goal_review': 'Independent AI review of the goal document; rework until it passes or a real conflict is recorded',
    'awaiting_confirmation': 'Human confirmation of the current goal document',
    'produce': 'Implement and verify each segment against real artifacts',
    'review': 'Independent AI review of the final result against the confirmed goals',
    'awaiting_final': 'Human review of the final result and its verification artifacts',
    'done': 'No remaining stage',
    'blocked': 'Resolve the recorded blocker, then resume',
    'failed': 'Repair the recorded failure, then resume',
}


class GuardError(ValueError):
    pass


def require(test, message):
    if not test:
        raise GuardError(message)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def utc_stamp():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def parse_stamp(value, message='Invalid timestamp'):
    require(nonempty(value), message)
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise GuardError(message)
    require(parsed.tzinfo is not None, message)
    return parsed


def read_json(path):
    with open(path, encoding='utf-8') as stream:
        return json.load(stream)


def digest(path):
    require(path.is_file(), 'Missing artifact: ' + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def atomic_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def atomic_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def artifact(base, name):
    require(nonempty(name), 'Artifact path must be nonempty')
    path = (base / name).resolve()
    return {'path': str(path), 'sha256': digest(path)}


def artifacts(base, values):
    require(isinstance(values, list), 'Expected artifact path list')
    result = [artifact(base, name) for name in values]
    require(len({v['path'] for v in result}) == len(result), 'Duplicate artifact')
    return result


def valid_artifact(item):
    return (isinstance(item, dict) and nonempty(item.get('path')) and isinstance(item.get('sha256'), str)
            and len(item['sha256']) == 64 and all(c in '0123456789abcdef' for c in item['sha256']))


def basis(state):
    return {key: state[key] for key in ('sources', 'intention', 'draft', 'evidence')}


def approved(state):
    return bool(state['intention'] and state['approval'] and
                state['approval']['intention_sha256'] == state['intention']['sha256'])


def goal_passed(state):
    review = state.get('goal_review')
    intention = state.get('intention')
    return bool(isinstance(review, dict) and review.get('verdict') == 'pass' and intention
                and review.get('intention_sha256') == intention['sha256'])


def event(state, action, detail):
    state['events'].append({'action': action, 'detail': detail})


def resolve_execution(request):
    task_type = request.get('task_type', 'unspecified')
    require(task_type in TASK_EXECUTION, 'task_type must be one of: ' + ', '.join(sorted(TASK_EXECUTION)))
    if 'execution_required' in request:
        require(isinstance(request.get('execution_required'), bool), 'execution_required must be true or false')
        return request['execution_required'], task_type
    return TASK_EXECUTION[task_type], task_type


def plan_defaults(state, execution_required=False, require_materials_map=False):
    """Additive execution-card fields. Missing legacy fields keep the bypass."""
    state.setdefault('plan', None)
    state.setdefault('step_records', {})
    state.setdefault('evidence_binder', None)
    state.setdefault('plan_invalidated', False)
    state.setdefault('execution_required', execution_required)
    state.setdefault('require_materials_map', require_materials_map)
    state.setdefault('materials_map', None)


def stage_defaults(state):
    state.setdefault('stage_started_at', None)
    state.setdefault('done_artifacts', [])


def gate_defaults(state):
    state.setdefault('task_type', 'unspecified')
    state.setdefault('goal_review', None)
    state.setdefault('final_approval', None)
    state.setdefault('segments', {})
    state.setdefault('rework_notes', None)
    state.setdefault('allowed_markdown', [])
    state.setdefault('notes_allowed', False)
    state.setdefault('notes_reason', None)
    state.setdefault('progress', None)


def normalize_plan(value):
    require(isinstance(value, dict) and value.get('frozen') is True,
            'Plan must be a JSON object marked frozen after user confirmation')
    raw_steps = value.get('steps')
    require(isinstance(raw_steps, list) and raw_steps, 'Plan needs a non-empty steps list')
    steps = []
    seen = set()
    for raw in raw_steps:
        require(isinstance(raw, dict), 'Invalid plan step')
        step_id = raw.get('id')
        require(nonempty(step_id) and step_id not in seen, 'Step id must be unique and nonempty')
        seen.add(step_id)
        for key in ('source', 'goal', 'action', 'verify', 'on_fail'):
            require(nonempty(raw.get(key)), 'Step ' + step_id + ' needs ' + key)
        require(raw.get('modality') in MODALITIES, 'Step ' + step_id + ' has invalid modality')
        require(isinstance(raw.get('screenshot_required'), bool), 'Step ' + step_id + ' needs boolean screenshot_required')
        must = raw.get('must_include', [])
        require(isinstance(must, list) and all(nonempty(x) for x in must), 'Step ' + step_id + ' needs string must_include')
        require(len(set(must)) == len(must), 'Step ' + step_id + ' has duplicate must_include')
        if raw['screenshot_required']:
            require(bool(must), 'Screenshot-required step ' + step_id + ' needs must_include')
        forbidden = raw.get('forbidden_shortcuts')
        require(isinstance(forbidden, list) and forbidden and all(nonempty(x) for x in forbidden),
                'Step ' + step_id + ' needs concrete forbidden_shortcuts')
        tool = raw.get('tool')
        require(tool is None or nonempty(tool), 'Step ' + step_id + ' has invalid tool')
        objects = raw.get('objects', [])
        require(isinstance(objects, list) and all(nonempty(x) for x in objects),
                'Step ' + step_id + ' has invalid objects')
        require(len(set(objects)) == len(objects), 'Step ' + step_id + ' has duplicate objects')
        evidence_ids = raw.get('evidence_ids', [])
        require(isinstance(evidence_ids, list) and all(nonempty(x) for x in evidence_ids),
                'Step ' + step_id + ' has invalid evidence_ids')
        if tool:
            require(any(tool in item for item in must),
                    'Step ' + step_id + ' declares tool "' + tool + '" but must_include never names it; '
                    'add an item such as "' + tool + ' window"')
        missing_objects = [item for item in objects if not any(item in text for text in must)]
        require(not missing_objects,
                'Step ' + step_id + ' objects missing from must_include: ' + ', '.join(missing_objects)
                + '; name every declared object in must_include')
        steps.append({'id': step_id, 'source': raw['source'], 'goal': raw['goal'],
                      'modality': raw['modality'], 'tool': tool, 'objects': objects,
                      'action': raw['action'],
                      'screenshot_required': raw['screenshot_required'], 'must_include': must,
                      'forbidden_shortcuts': forbidden, 'verify': raw['verify'],
                      'on_fail': raw['on_fail'], 'evidence_ids': evidence_ids})
    return steps


def binder_payload(state):
    plan = state['plan']
    require(plan is not None, 'No frozen plan')
    steps = {}
    for step in plan['steps']:
        record = state['step_records'].get(step['id'])
        require(record is not None, 'Missing completed step: ' + step['id'])
        steps[step['id']] = {
            'modality': step['modality'],
            'screenshot_required': step['screenshot_required'],
            'must_include': record['must_include'],
            'evidence': [{'path': item['path'], 'sha256': item['sha256']} for item in record['evidence']],
        }
        if step.get('tool'):
            steps[step['id']]['tool'] = step['tool']
        if step.get('objects'):
            steps[step['id']]['objects'] = step['objects']
    return {'plan_sha256': plan['sha256'], 'steps': steps}


def plan_ready_for_submit(state):
    plan = state['plan']
    if plan is None:
        return True
    require(plan.get('frozen') is True, 'Freeze the execution card before writing')
    missing = [step['id'] for step in plan['steps'] if step['id'] not in state['step_records']]
    require(not missing, 'Complete all execution-card steps before writing: ' + ', '.join(missing))
    binder = state['evidence_binder']
    require(isinstance(binder, dict) and binder.get('status') == 'ok'
            and binder.get('plan_sha256') == plan['sha256']
            and binder.get('summary_sha256') == canonical_sha(binder_payload(state)),
            'Bind current step evidence before writing')
    return True


def segments_ready(state):
    pending = [sid for sid, rec in state.get('segments', {}).items() if rec.get('status') != 'verified']
    require(not pending, 'Verify every segment before submit_draft: ' + ', '.join(sorted(pending)))


def review_gate(state, base, required=()):
    """Check the independent-review input whitelist before a final receipt is recorded."""
    missing = []
    if state['require_materials_map']:
        record = state.get('materials_map')
        if record is None:
            missing.append('MATERIALS_MAP.md (register_materials_map)')
        elif not Path(record['path']).is_file():
            missing.append('materials map file: ' + record['path'])
    intention = state.get('intention')
    if intention is None:
        missing.append('confirmed intention (submit_intention + confirm)')
    elif not Path(intention['path']).is_file():
        missing.append('intention file: ' + intention['path'])
    if state['execution_required']:
        plan = state.get('plan')
        if plan is None:
            missing.append('frozen execution card (freeze_plan)')
        else:
            if not Path(plan['path']).is_file():
                missing.append('execution card file: ' + plan['path'])
            uncompleted = [step['id'] for step in plan.get('steps', [])
                           if step['id'] not in state['step_records']]
            if uncompleted:
                missing.append('uncompleted execution-card steps: ' + ', '.join(uncompleted))
            binder = state.get('evidence_binder')
            if not (isinstance(binder, dict) and binder.get('status') == 'ok'):
                missing.append('evidence binder (bind_evidence)')
    if not state.get('draft'):
        missing.append('candidate draft (submit_draft)')
    else:
        for item in state['draft']:
            if not Path(item['path']).is_file():
                missing.append('draft file: ' + item['path'])
    require(isinstance(required, (list, tuple)) and all(nonempty(name) for name in required),
            'required must be a list of nonempty paths')
    for name in required:
        path = (base / name).resolve()
        if not path.is_file():
            missing.append('required path: ' + str(path))
    require(not missing, 'Review input whitelist incomplete; missing: ' + '; '.join(missing))
    return {'ok': True, 'extra_required': list(required)}


def done_gate(state, base, names):
    """Refuse a DONE claim unless it names real, non-empty, current-stage artifacts."""
    require(isinstance(names, list) and names and all(nonempty(name) for name in names),
            'finish needs artifacts: a non-empty list of the deliverable paths actually produced')
    started = None if state.get('stage_started_at') is None else parse_stamp(
        state['stage_started_at'], 'Invalid stage start timestamp')
    problems = []
    records = []
    seen = set()
    for name in names:
        path = (base / name).resolve()
        key = str(path)
        if key in seen:
            problems.append('duplicate artifact: ' + key)
            continue
        seen.add(key)
        if not path.is_file():
            problems.append('missing artifact: ' + key)
            continue
        stat = path.stat()
        if stat.st_size <= 0:
            problems.append('empty artifact: ' + key)
            continue
        mtime = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        if started is not None and mtime <= started:
            problems.append('stale artifact older than this stage started at ' + state['stage_started_at'] + ': ' + key)
            continue
        records.append({'path': key, 'sha256': digest(path), 'size': stat.st_size,
                        'mtime': mtime.isoformat(timespec='microseconds')})
    require(not problems, 'DONE artifact check failed: ' + '; '.join(problems))
    return records


def validate_stage(state):
    started = state.get('stage_started_at')
    if started is not None:
        require(isinstance(started, str), 'Invalid stage start timestamp')
        parse_stamp(started, 'Invalid stage start timestamp')
    done = state.get('done_artifacts')
    require(isinstance(done, list), 'Invalid done artifact list')
    for item in done:
        require(valid_artifact(item) and type(item.get('size')) is int and item['size'] > 0
                and nonempty(item.get('mtime')), 'Invalid done artifact record')
        parse_stamp(item['mtime'], 'Invalid done artifact mtime')
    if state['phase'] == 'done':
        for item in done:
            path = Path(item['path'])
            require(path.is_file(), 'Declared done artifact is missing: ' + item['path'])
            require(path.stat().st_size > 0, 'Declared done artifact is empty: ' + item['path'])


def validate_plan_state(state):
    require(isinstance(state.get('execution_required'), bool), 'Invalid execution_required marker')
    require(isinstance(state.get('require_materials_map'), bool), 'Invalid materials-map gate marker')
    materials_map = state.get('materials_map')
    require(materials_map is None or valid_artifact(materials_map), 'Invalid materials map record')
    require(isinstance(state.get('step_records'), dict), 'Invalid step records')
    require(isinstance(state.get('plan_invalidated'), bool), 'Invalid plan invalidation marker')
    binder = state.get('evidence_binder')
    require(binder is None or isinstance(binder, dict), 'Invalid evidence binder')
    plan = state.get('plan')
    if plan is None:
        require(not state['step_records'] and binder is None, 'Step progress without a frozen plan')
        require(not state['execution_required'] or state['phase'] not in {'review', 'awaiting_final', 'done'},
                'execution_required task has no frozen execution card; freeze_plan before writing')
        if state['phase'] in {'review', 'awaiting_final', 'done'}:
            require(not state['plan_invalidated'], 'Refreeze the changed execution card before writing')
        return
    require(state['plan_invalidated'] is False, 'Refreeze the changed execution card before continuing')
    require(isinstance(plan, dict) and nonempty(plan.get('path')) and isinstance(plan.get('sha256'), str)
            and len(plan['sha256']) == 64 and plan.get('frozen') is True and nonempty(plan.get('message_ref'))
            and plan.get('intention_sha256') == (state.get('intention') or {}).get('sha256')
            and isinstance(plan.get('steps'), list) and plan['steps'], 'Invalid frozen plan record')
    ids = [step.get('id') for step in plan['steps']]
    require(all(nonempty(step_id) for step_id in ids) and len(set(ids)) == len(ids), 'Invalid plan step ids')
    for step in plan['steps']:
        require(isinstance(step, dict) and step.get('modality') in MODALITIES
                and isinstance(step.get('screenshot_required'), bool)
                and isinstance(step.get('must_include'), list)
                and isinstance(step.get('forbidden_shortcuts'), list), 'Invalid plan step')
        require(step.get('tool') is None or nonempty(step.get('tool')), 'Invalid plan step tool')
        require(isinstance(step.get('objects', []), list)
                and all(nonempty(item) for item in step.get('objects', [])), 'Invalid plan step objects')
    for step_id, record in state['step_records'].items():
        require(step_id in ids and isinstance(record, dict) and isinstance(record.get('evidence'), list)
                and record['evidence'] and all(valid_artifact(item) for item in record['evidence'])
                and isinstance(record.get('must_include'), dict), 'Invalid completed step record')
    if binder is not None:
        require(binder.get('status') == 'ok' and binder.get('plan_sha256') == plan['sha256']
                and binder.get('summary_sha256') == canonical_sha(binder_payload(state)),
                'Evidence binder does not match current plan/steps')
    if state['phase'] in {'review', 'awaiting_final', 'done'}:
        plan_ready_for_submit(state)


def validate_segments(state):
    segments = state.get('segments')
    require(isinstance(segments, dict), 'Invalid segments')
    running = {}
    for sid, rec in segments.items():
        require(nonempty(sid) and isinstance(rec, dict), 'Invalid segment')
        require(rec.get('status') in SEGMENT_STATUSES, 'Invalid segment status: ' + sid)
        resource = rec.get('exclusive_resource')
        require(resource is None or nonempty(resource), 'Invalid exclusive resource: ' + sid)
        deps = rec.get('depends_on', [])
        require(isinstance(deps, list) and all(nonempty(item) for item in deps), 'Invalid segment dependencies: ' + sid)
        if rec['status'] == 'running':
            require(nonempty(rec.get('owner')), 'Running segment needs an owner: ' + sid)
            if resource:
                require(resource not in running, 'Two segments are running on exclusive resource ' + resource)
                running[resource] = sid
        if rec['status'] == 'verified':
            require(isinstance(rec.get('evidence'), list) and rec['evidence']
                    and all(valid_artifact(item) for item in rec['evidence']),
                    'Verified segment needs evidence: ' + sid)
    for sid, rec in segments.items():
        for dep in rec.get('depends_on', []):
            require(dep in segments and dep != sid, 'Unknown segment dependency: ' + dep)


def validate_goal_review(state):
    review = state.get('goal_review')
    require(review is None or isinstance(review, dict), 'Invalid goal review')
    if not review:
        return
    require(review.get('verdict') in {'pass', 'rework', 'conflict'}, 'Invalid goal-review verdict')
    intention = state.get('intention') or {}
    require(review.get('intention_sha256') == intention.get('sha256'), 'Goal review is not bound to the current intention')
    if review.get('legacy'):
        require(review.get('verdict') == 'pass', 'Legacy goal review must be a pass marker')
        return
    require(valid_artifact(review.get('receipt')), 'Invalid goal-review receipt')


def validate_final_approval(state):
    approval = state.get('final_approval')
    require(approval is None or isinstance(approval, dict), 'Invalid final approval')
    if state['phase'] == 'awaiting_final':
        require(state.get('review') and state['review']['basis'] == basis(state), 'Final gate needs a current AI review')
    if state['phase'] == 'done':
        require(isinstance(approval, dict) and nonempty(approval.get('message_ref')), 'Done requires the final human gate')
        if not approval.get('legacy'):
            require(state.get('review') and approval.get('review_sha256') == state['review']['receipt']['sha256'],
                    'Final human gate is not bound to the current AI review')


def validate_base(state, schema):
    require(isinstance(state, dict) and state.get('schema') == schema, 'Unsupported state schema')
    require(state.get('phase') in PHASES and nonempty(state.get('maker')), 'Invalid phase/maker')
    for key in ('sources', 'draft', 'evidence'):
        require(isinstance(state.get(key), list), 'Invalid artifact collection: ' + key)
    require(state.get('intention') is None or isinstance(state['intention'], dict), 'Invalid intention')
    for item in state['sources'] + state['draft'] + state['evidence'] + ([state['intention']] if state['intention'] else []):
        require(valid_artifact(item), 'Invalid artifact record')
    require(isinstance(state.get('events'), list), 'Invalid events')
    require(isinstance(state.get('impact_pending'), bool), 'Invalid impact marker')
    require(state.get('approval') is None or (isinstance(state['approval'], dict)
            and nonempty(state['approval'].get('message_ref')) and nonempty(state['approval'].get('intention_sha256'))),
            'Invalid approval')
    require(state.get('review') is None or (isinstance(state['review'], dict) and 'receipt' in state['review']
            and 'basis' in state['review']), 'Invalid review')
    require(not state['impact_pending'] or state['phase'] in {'blocked', 'failed', 'intake'}, 'Unresolved source impact')
    hold = state.get('hold')
    require(hold is None or (isinstance(hold, dict) and hold.get('kind') in {'blocked', 'failed'}
            and nonempty(hold.get('reason')) and state['phase'] == hold['kind']), 'Invalid execution hold')
    if state['phase'] in {'awaiting_confirmation', 'produce', 'review', 'awaiting_final', 'done'}:
        require(goal_passed(state), 'Goal review pass is not bound to the current intention')
    if state['phase'] in {'produce', 'review', 'awaiting_final', 'done'}:
        require(approved(state), 'No approval for current intention')
    if state['phase'] in {'review', 'awaiting_final', 'done'}:
        require(bool(state['draft']), 'No candidate artifact')
    if state['phase'] in {'awaiting_final', 'done'}:
        require(state['review'] is not None and state['review']['basis'] == basis(state), 'No current review')
    if state['phase'] in {'blocked', 'failed'}:
        require(nonempty(state.get('waiting_reason')) and state.get('resume_phase') in PHASES - {'blocked', 'failed'},
                'Invalid paused state')


def validate(state):
    validate_base(state, 3)
    require(state.get('task_type') in TASK_EXECUTION, 'Invalid task_type')
    require(isinstance(state.get('notes_allowed'), bool), 'Invalid notes flag')
    require(state.get('notes_reason') is None or nonempty(state.get('notes_reason')), 'Invalid notes reason')
    require(isinstance(state.get('allowed_markdown'), list), 'Invalid markdown allowlist')
    for item in state['allowed_markdown']:
        require(isinstance(item, dict) and nonempty(item.get('path')) and nonempty(item.get('reason')),
                'Invalid markdown allowlist entry')
    validate_goal_review(state)
    validate_final_approval(state)
    validate_segments(state)
    validate_plan_state(state)
    validate_stage(state)
    segments_ready_ok = not any(rec.get('status') != 'verified' for rec in state['segments'].values())
    if state['phase'] in {'review', 'awaiting_final', 'done'} and state['segments']:
        require(segments_ready_ok, 'Unverified segments cannot enter review')


def upgrade(state):
    """Peel memory-ledger fields off schema 1 or 2 and land schema 3.

    In-progress tasks that already passed the old intention gate keep a legacy
    goal-review marker so they are not forced back through a review that did
    not exist yet. Completed tasks keep a legacy final-gate marker. New tasks
    never receive either marker.
    """
    old = state.get('schema')
    if old == 3:
        return False
    require(old in {1, 2}, 'Unsupported state schema')
    for key in MEMORY_KEYS:
        state.pop(key, None)
    state['schema'] = 3
    plan_defaults(state)
    stage_defaults(state)
    gate_defaults(state)
    past_goal = {'awaiting_confirmation', 'produce', 'review', 'awaiting_final', 'done'}
    if state.get('intention') and (state.get('phase') in past_goal or state.get('resume_phase') in past_goal):
        if not goal_passed(state):
            state['goal_review'] = {
                'legacy': True,
                'verdict': 'pass',
                'intention_sha256': state['intention']['sha256'],
                'receipt': None,
            }
    if state.get('phase') == 'done' and state.get('review') and not state.get('final_approval'):
        state['final_approval'] = {
            'legacy': True,
            'message_ref': 'legacy-schema-bypass',
            'review_sha256': state['review']['receipt']['sha256'],
        }
    return True


def preserve_hold(state):
    if state.get('hold'):
        if state['phase'] not in {'blocked', 'failed'}:
            state['resume_phase'] = state['phase']
        state.update(phase=state['hold']['kind'], waiting_reason=state['hold']['reason'])


def reconcile(state):
    changed = []
    for key in ('sources', 'intention', 'draft', 'evidence'):
        items = [state[key]] if key == 'intention' and state[key] else ([] if key == 'intention' else state[key])
        for item in items:
            current = digest(Path(item['path']))
            if current != item['sha256']:
                changed.append(key)
                item['sha256'] = current
    review = state.get('goal_review')
    if isinstance(review, dict) and not review.get('legacy') and review.get('receipt'):
        if digest(Path(review['receipt']['path'])) != review['receipt']['sha256']:
            state['goal_review'] = None
            state['approval'] = None
            changed.append('goal_review')
    plan = state.get('plan')
    if plan:
        intention_sha = state['intention']['sha256'] if state['intention'] else None
        if digest(Path(plan['path'])) != plan['sha256'] or plan.get('intention_sha256') != intention_sha:
            state.update(plan=None, step_records={}, evidence_binder=None, plan_invalidated=True)
            changed.append('plan')
    for step_id, record in list(state.get('step_records', {}).items()):
        if any(digest(Path(item['path'])) != item['sha256'] for item in record['evidence']):
            del state['step_records'][step_id]
            state['evidence_binder'] = None
            changed.append('step_evidence')
    for sid, rec in list(state.get('segments', {}).items()):
        if rec.get('status') == 'verified' and any(digest(Path(item['path'])) != item['sha256'] for item in rec.get('evidence', [])):
            rec.update(status='rework', evidence=[], owner=None)
            changed.append('segment_evidence')
    if changed:
        state['review'] = None
        state['final_approval'] = None
        if 'intention' in changed or 'goal_review' in changed:
            state['approval'] = None
            if 'intention' in changed:
                state['goal_review'] = None
        if 'sources' in changed or state['impact_pending']:
            state.update(phase='blocked', resume_phase='produce' if approved(state) else 'goal_review',
                         waiting_reason='Source files changed; assess impact before proceeding', impact_pending=True)
        elif 'plan' in changed or 'step_evidence' in changed or 'evidence' in changed or 'segment_evidence' in changed:
            state.update(phase='produce' if approved(state) else 'goal_review',
                         waiting_reason=None, resume_phase=None)
        elif 'intention' in changed or 'goal_review' in changed:
            state.update(phase='goal_review', waiting_reason=None, resume_phase=None)
        else:
            state.update(phase='review' if approved(state) and state['draft'] else
                         ('produce' if approved(state) else 'goal_review'),
                         waiting_reason=None, resume_phase=None)
        event(state, 'invalidate', sorted(set(changed)))
    if state['review'] and digest(Path(state['review']['receipt']['path'])) != state['review']['receipt']['sha256']:
        state.update(review=None, final_approval=None, phase='review', waiting_reason=None, resume_phase=None)
        changed.append('review_receipt')
        event(state, 'invalidate', ['review_receipt'])
    if changed and state.get('hold'):
        preserve_hold(state)
    return changed


def string_list(request, key):
    if key not in request:
        return None
    value = request[key]
    require(isinstance(value, list) and value and all(nonempty(item) for item in value),
            key + ' must be a nonempty list of strings')
    return list(value)


def render_progress(state, done, remaining, blockers, updated):
    lines = ['# STATUS', '', '- stage: ' + state['phase'], '- updated: ' + updated, '', '## done', '']
    lines += ['- ' + item for item in done]
    lines += ['', '## remaining', '']
    lines += ['- ' + item for item in remaining]
    lines += ['', '## blockers', '']
    lines += ['- ' + item for item in blockers]
    lines.append('')
    return '\n'.join(lines)


def write_progress(base, state, request):
    done = string_list(request, 'progress_done')
    remaining = string_list(request, 'progress_remaining')
    blockers = string_list(request, 'progress_blockers')
    if done is None:
        done = [item['action'] for item in state['events'][-5:]] or ['initialized']
    if remaining is None:
        remaining = [PHASE_REMAINING[state['phase']]]
    if blockers is None:
        blockers = [state['waiting_reason']] if state.get('waiting_reason') else ['none']
    updated = utc_stamp()
    text = render_progress(state, done, remaining, blockers, updated)
    atomic_text(base / 'progress' / 'STATUS.md', text)
    state['progress'] = {'done': done, 'remaining': remaining, 'blockers': blockers, 'updated': updated}
    return text


def progress_status_ok(text, phase):
    """Return a list of contract problems. Empty means the file matches the contract."""
    problems = []
    if not text.startswith('# STATUS\n'):
        problems.append('missing # STATUS heading')
    if '\n- stage: ' + phase + '\n' not in '\n' + text:
        problems.append('stage line does not match ' + phase)
    for heading in ('## done', '## remaining', '## blockers'):
        if '\n' + heading + '\n' not in '\n' + text:
            problems.append('missing ' + heading)
    if '- updated: ' not in text:
        problems.append('missing updated stamp')
    return problems


def allowed_markdown_paths(state, base):
    allowed = {(base / 'progress' / 'STATUS.md').resolve(), (base / 'MATERIALS_MAP.md').resolve()}
    if state.get('notes_allowed'):
        allowed.add((base / 'NOTES.md').resolve())
    intention = state.get('intention')
    if isinstance(intention, dict) and intention.get('path'):
        allowed.add(Path(intention['path']).resolve())
    materials = state.get('materials_map')
    if isinstance(materials, dict) and materials.get('path'):
        allowed.add(Path(materials['path']).resolve())
    for item in state.get('allowed_markdown') or []:
        allowed.add((base / item['path']).resolve())
    return allowed


def check_markdown(state, base):
    allowed = allowed_markdown_paths(state, base)
    unknown = []
    if base.is_dir():
        for path in base.rglob('*.md'):
            if path.resolve() not in allowed:
                unknown.append(str(path.resolve()))
    require(not unknown,
            'Unsolicited markdown is not allowed: ' + '; '.join(sorted(unknown))
            + '. Allowed files are the goal document, progress/STATUS.md, MATERIALS_MAP.md, '
            + 'NOTES.md only after allow_notes, and paths recorded with allow_markdown.')
    return {'ok': True, 'allowed': sorted(str(path) for path in allowed)}


def load_resource_lock():
    spec = importlib.util.spec_from_file_location('tasks_killer_resource_lock', Path(__file__).with_name('resource_lock.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lock_status(base, name, owner):
    module = load_resource_lock()
    path = (base / name).resolve()
    try:
        report = module.status(path, owner=owner)
    except module.LockError as error:
        raise GuardError(str(error))
    return report


def require_live_lock(base, name, owner):
    report = lock_status(base, name, owner)
    require(report['held'] and not report['stale'] and report['owner_matches'] is True,
            'Exclusive segment needs a live resource lock held by ' + owner)
    return report


def normalize_segments(value):
    require(isinstance(value, list) and value, 'segments must be a non-empty list')
    segments = {}
    for raw in value:
        require(isinstance(raw, dict), 'Invalid segment')
        sid = raw.get('id')
        require(nonempty(sid) and sid not in segments, 'Segment id must be unique and nonempty')
        resource = raw.get('exclusive_resource')
        require(resource is None or nonempty(resource), 'exclusive_resource must be a string or null')
        deps = raw.get('depends_on', [])
        require(isinstance(deps, list) and all(nonempty(item) for item in deps), 'depends_on must be a list of ids')
        segments[sid] = {'status': 'pending', 'exclusive_resource': resource, 'depends_on': list(deps),
                         'owner': None, 'evidence': [], 'lock_path': None}
    for sid, rec in segments.items():
        for dep in rec['depends_on']:
            require(dep in segments and dep != sid, 'Unknown segment dependency: ' + dep)
    return segments


def findings_ok(receipt, require_pass):
    findings = receipt.get('findings')
    require(isinstance(findings, list) and findings, 'Review findings must be a nonempty list')
    for item in findings:
        require(isinstance(item, dict) and nonempty(item.get('reason')) and item.get('status') in {'pass', 'fail'},
                'Each finding needs status pass or fail and a reason')
        if require_pass:
            require(item.get('status') == 'pass', 'A passing review cannot contain a failing finding')
    return findings


def review_record(base, state, name):
    record = artifact(base, name)
    receipt = read_json(record['path'])
    require(isinstance(receipt, dict), 'Invalid review receipt')
    require(nonempty(receipt.get('reviewer')) and receipt['reviewer'] != state['maker'], 'Independent reviewer identity required')
    require(nonempty(receipt.get('context_ref')), 'Independent context/session reference required')
    require(receipt.get('basis') == basis(state), 'Review is not bound to current files')
    require(receipt.get('verdict') == 'pass', 'Review did not pass; revise affected work')
    checks = receipt.get('checks')
    require(isinstance(checks, dict) and CHECKS <= checks.keys(), 'Missing required review checks')
    for key in CHECKS:
        item = checks[key]
        require(isinstance(item, dict) and item.get('status') in {'pass', 'not_applicable'}
                and nonempty(item.get('reason')), 'Unresolved/unsupported review check: ' + key)
        require(key not in {'requirements', 'writing', 'final_file'} or item['status'] == 'pass',
                'Required check cannot be not_applicable: ' + key)
    return {'receipt': record, 'basis': basis(state)}


def apply(state, request, base):
    action = request.get('action')
    phase = state['phase']
    if action == 'status':
        return
    if action == 'submit_intention':
        require(phase in {'intake', 'goal_review', 'awaiting_confirmation'}, 'Return to intake to change scope')
        if state['require_materials_map']:
            record = state['materials_map']
            require(record is not None,
                    'No MATERIALS_MAP.md registered; run register_materials_map before submit_intention '
                    '(or disable the gate with set_require_materials_map and a reason)')
            map_path = Path(record['path'])
            require(map_path.is_file(), 'Registered materials map is missing: ' + record['path'] + '; re-register the actual file')
            require(digest(map_path) == record['sha256'],
                    'Materials map changed since registration; re-register the current file before submitting the intention')
            map_ids = request.get('map_ids')
            require(isinstance(map_ids, list) and map_ids and all(nonempty(item) for item in map_ids),
                    'submit_intention needs map_ids: a nonempty list of MATERIALS_MAP.md ids referenced by hard requirements')
            map_text = map_path.read_text(encoding='utf-8', errors='replace')
            unknown = [item for item in map_ids if item not in map_text]
            require(not unknown, 'map_ids not found in the materials map: ' + ', '.join(unknown))
        plan_was_frozen = state['plan'] is not None
        state.update(intention=artifact(base, request.get('path')), approval=None, review=None, goal_review=None,
                     final_approval=None, phase='goal_review', plan=None, step_records={}, evidence_binder=None,
                     plan_invalidated=state['plan_invalidated'] or plan_was_frozen)
        check_markdown(state, base)
    elif action == 'record_goal_review':
        require(phase == 'goal_review' and state.get('intention'), 'Goal review runs after submit_intention and before the human gate')
        record = artifact(base, request.get('path'))
        receipt = read_json(record['path'])
        require(isinstance(receipt, dict), 'Invalid goal-review receipt')
        require(receipt.get('target') == 'goal', 'Goal-review receipt must set target to goal')
        require(nonempty(receipt.get('reviewer')) and receipt['reviewer'] != state['maker'], 'Independent goal reviewer identity required')
        require(nonempty(receipt.get('context_ref')), 'Independent goal-review context reference required')
        require(receipt.get('intention_sha256') == state['intention']['sha256'], 'Goal review is not bound to the current intention')
        verdict = receipt.get('verdict')
        require(verdict in {'pass', 'rework', 'conflict'}, 'Goal-review verdict must be pass, rework, or conflict')
        findings_ok(receipt, require_pass=verdict == 'pass')
        state['goal_review'] = {'receipt': record, 'intention_sha256': state['intention']['sha256'],
                                'verdict': verdict, 'legacy': False}
        state['approval'] = None
        if verdict == 'pass':
            state.update(phase='awaiting_confirmation', waiting_reason=None, resume_phase=None, hold=None)
        elif verdict == 'rework':
            state.update(phase='goal_review', waiting_reason=None, resume_phase=None)
        else:
            reason = receipt.get('conflict')
            require(nonempty(reason), 'A goal-review conflict needs a concrete conflict string')
            state.update(phase='blocked', resume_phase='goal_review', waiting_reason=reason,
                         hold={'kind': 'blocked', 'reason': reason})
    elif action == 'register_materials_map':
        require(phase in {'intake', 'goal_review', 'awaiting_confirmation'},
                'Register the materials map before confirming the intention; rerun intake to change it later')
        state['materials_map'] = artifact(base, request.get('path'))
        state['review'] = None
    elif action == 'set_require_materials_map':
        require(phase in {'intake', 'goal_review', 'awaiting_confirmation'},
                'Set the materials-map gate before confirming the intention; rerun intake to change it later')
        require(isinstance(request.get('require_materials_map'), bool) and nonempty(request.get('reason')),
                'Set require_materials_map true/false with a concrete reason')
        state['require_materials_map'] = request['require_materials_map']
    elif action == 'set_execution_required':
        require(phase in {'intake', 'goal_review', 'awaiting_confirmation'},
                'Set execution_required before confirming the intention; rerun intake to change it after execution starts')
        require(isinstance(request.get('execution_required'), bool) and nonempty(request.get('reason')),
                'Set execution_required true/false with a concrete reason')
        state['execution_required'] = request['execution_required']
    elif action == 'allow_notes':
        require(nonempty(request.get('reason')), 'allow_notes needs the reason a check cannot encode this yet')
        state['notes_allowed'] = True
        state['notes_reason'] = request['reason']
    elif action == 'allow_markdown':
        require(nonempty(request.get('path')) and nonempty(request.get('reason')),
                'allow_markdown needs a path and the reason the task or user required that file')
        state['allowed_markdown'].append({'path': request['path'], 'reason': request['reason']})
    elif action == 'markdown_gate':
        check_markdown(state, base)
    elif action == 'confirm':
        require(phase == 'awaiting_confirmation' and state['intention'] and not state['impact_pending'],
                'No ready intention to confirm')
        require(goal_passed(state), 'Independent AI review of the goal must pass before the human gate')
        require(nonempty(request.get('message_ref')), 'Supply actual user confirmation reference; silence is not confirmation')
        check_markdown(state, base)
        state.update(approval={'message_ref': request['message_ref'], 'intention_sha256': state['intention']['sha256']},
                     phase='produce')
    elif action == 'register_segments':
        require(phase == 'produce' and approved(state), 'Register segments after the goal document is confirmed')
        running = [sid for sid, rec in state['segments'].items() if rec['status'] == 'running']
        require(not running, 'Cannot replace segments while some are running: ' + ', '.join(running))
        if state['segments']:
            require(nonempty(request.get('reason')), 'Replacing a segment map needs a reason')
        state['segments'] = normalize_segments(request.get('segments'))
        state['review'] = None
        state['final_approval'] = None
    elif action == 'claim_segment':
        require(phase == 'produce' and approved(state), 'Claim segments while producing')
        sid = request.get('id')
        owner = request.get('owner')
        require(nonempty(sid) and sid in state['segments'], 'Unknown segment')
        require(nonempty(owner), 'Segment claim needs an owner')
        rec = state['segments'][sid]
        require(rec['status'] in {'pending', 'rework'}, 'Segment is not claimable: ' + sid)
        for dep in rec['depends_on']:
            require(state['segments'][dep]['status'] == 'verified', 'Dependency is not verified: ' + dep)
        resource = rec['exclusive_resource']
        if resource:
            holders = [other for other, item in state['segments'].items()
                       if other != sid and item.get('exclusive_resource') == resource and item['status'] == 'running']
            require(not holders, 'Exclusive resource ' + resource + ' is held by ' + ', '.join(holders))
            require(nonempty(request.get('lock_path')), 'Exclusive segment claim needs lock_path from resource_lock.py')
            require_live_lock(base, request['lock_path'], owner)
            rec['lock_path'] = request['lock_path']
        else:
            require(request.get('lock_path') in (None, ''), 'A non-exclusive segment must not hold a resource lock')
            rec['lock_path'] = None
        rec.update(status='running', owner=owner, evidence=[])
    elif action == 'verify_segment':
        require(phase == 'produce' and approved(state), 'Verify segments while producing')
        sid = request.get('id')
        require(nonempty(sid) and sid in state['segments'], 'Unknown segment')
        rec = state['segments'][sid]
        require(rec['status'] == 'running', 'Verify only a running segment: ' + sid)
        require(request.get('owner') == rec['owner'], 'Only the claiming owner may verify segment ' + sid)
        if rec['exclusive_resource']:
            require_live_lock(base, rec['lock_path'], rec['owner'])
        evidence = artifacts(base, request.get('evidence', []))
        require(bool(evidence), 'Segment verification needs at least one real artifact')
        for item in evidence:
            require(Path(item['path']).stat().st_size > 0, 'Evidence file is empty: ' + item['path'])
        rec.update(status='verified', evidence=evidence)
    elif action == 'rework_segment':
        require(phase == 'produce' and approved(state), 'Rework segments while producing')
        sid = request.get('id')
        require(nonempty(sid) and sid in state['segments'], 'Unknown segment')
        require(nonempty(request.get('reason')), 'Segment rework needs a reason')
        rec = state['segments'][sid]
        require(rec['status'] in {'running', 'verified'}, 'Segment is not in a reworkable state: ' + sid)
        rec.update(status='rework', evidence=[], owner=None, lock_path=None)
        state['review'] = None
        state['final_approval'] = None
    elif action == 'recover_segment':
        require(nonempty(request.get('id')) and nonempty(request.get('reason')), 'Recovery needs a segment id and a reason')
        require(request.get('stale') is True, 'recover_segment only applies after the worker or its lock is stale')
        sid = request['id']
        require(sid in state['segments'], 'Unknown segment')
        rec = state['segments'][sid]
        require(rec['status'] == 'running', 'Only a running segment can be recovered: ' + sid)
        if rec['exclusive_resource'] and rec.get('lock_path'):
            report = lock_status(base, rec['lock_path'], rec.get('owner') or '')
            require((not report['held']) or report['stale'],
                    'Live lock cannot be recovered; release it or break-stale with a reason first')
        rec.update(status='rework', evidence=[], owner=None, lock_path=None)
    elif action == 'freeze_plan':
        require(phase == 'produce' and approved(state), 'Freeze the execution card under a confirmed intention')
        require(nonempty(request.get('message_ref')), 'Supply the actual user confirmation reference for the card')
        if state['plan'] is not None or state['plan_invalidated']:
            require(nonempty(request.get('reason')), 'Editing/refreezing a card needs a reason and affected scope')
        record = artifact(base, request.get('path'))
        steps = normalize_plan(read_json(record['path']))
        state.update(plan={'path': record['path'], 'sha256': record['sha256'], 'frozen': True,
                           'message_ref': request['message_ref'], 'intention_sha256': state['intention']['sha256'],
                           'steps': steps},
                     step_records={}, evidence_binder=None, plan_invalidated=False, review=None, final_approval=None)
    elif action == 'complete_step':
        require(phase == 'produce' and approved(state), 'Complete steps while producing under a confirmed intention')
        plan = state['plan']
        require(plan is not None and plan.get('frozen') is True, 'Freeze the execution card before completing steps')
        step_id = request.get('id')
        step = next((item for item in plan['steps'] if item['id'] == step_id), None)
        require(step is not None, 'Unknown execution-card step')
        require(step_id not in state['step_records'], 'Step already completed: ' + step_id)
        evidence = artifacts(base, request.get('evidence', []))
        require(bool(evidence), 'Step completion needs at least one evidence file')
        for item in evidence:
            require(Path(item['path']).stat().st_size > 0, 'Evidence file is empty: ' + item['path'])
        if step['screenshot_required']:
            require(any(Path(item['path']).suffix.lower() in IMAGE_SUFFIXES for item in evidence),
                    'Screenshot-required step needs an image evidence file')
        marks = request.get('must_include')
        if step['must_include']:
            require(isinstance(marks, dict) and set(marks) == set(step['must_include']),
                    'Mark every must_include item for step ' + step_id)
            for key, value in marks.items():
                passed = value == 'pass' or (isinstance(value, dict) and value.get('status') == 'pass')
                require(passed, 'must_include not passed: ' + key)
        else:
            require(marks in (None, {}), 'Step ' + step_id + ' declares no must_include items')
        state['step_records'][step_id] = {'evidence': evidence,
                                          'must_include': {key: 'pass' for key in step['must_include']}}
        state['evidence_binder'] = None
        state['review'] = None
        state['final_approval'] = None
    elif action == 'bind_evidence':
        require(phase == 'produce' and approved(state), 'Bind evidence while producing under a confirmed intention')
        plan = state['plan']
        require(plan is not None and plan.get('frozen') is True, 'Freeze the execution card before binding evidence')
        missing = [step['id'] for step in plan['steps'] if step['id'] not in state['step_records']]
        require(not missing, 'Complete all execution-card steps before binding: ' + ', '.join(missing))
        state['evidence_binder'] = {'status': 'ok', 'plan_sha256': plan['sha256'],
                                    'summary_sha256': canonical_sha(binder_payload(state))}
        state['review'] = None
        state['final_approval'] = None
    elif action == 'submit_draft':
        require(phase == 'produce' and approved(state), 'Production requires confirmed intention')
        require(not state['plan_invalidated'], 'Refreeze the changed execution card before writing')
        if state['execution_required']:
            require(state['plan'] is not None,
                    'This task declares execution_required: freeze_plan a confirmed execution card before submit_draft')
            plan_ready_for_submit(state)
        elif state['plan'] is not None:
            plan_ready_for_submit(state)
        segments_ready(state)
        candidate = artifacts(base, request.get('paths'))
        require(bool(candidate), 'Candidate cannot be empty')
        state.update(draft=candidate, evidence=artifacts(base, request.get('evidence', [])),
                     review=None, final_approval=None, phase='review')
    elif action == 'review_gate':
        require(phase in {'review', 'awaiting_final', 'done'}, 'Review gate runs after submit_draft; produce the candidate first')
        review_gate(state, base, request.get('required', []))
    elif action == 'record_review':
        require(phase == 'review', 'Not ready for review')
        review_gate(state, base, request.get('required', []))
        receipt_path = artifact(base, request.get('path'))
        receipt = read_json(receipt_path['path'])
        verdict = receipt.get('verdict') if isinstance(receipt, dict) else None
        if verdict == 'rework':
            findings_ok(receipt, require_pass=False)
            require(any(item.get('status') == 'fail' for item in receipt['findings']), 'Rework needs at least one failing finding')
            state['rework_notes'] = {'receipt': receipt_path, 'findings': receipt['findings']}
            state.update(review=None, final_approval=None, phase='produce')
        elif verdict == 'conflict':
            reason = receipt.get('conflict')
            require(nonempty(reason), 'A final-review conflict needs a concrete conflict string')
            state.update(review=None, final_approval=None, phase='blocked', resume_phase='review',
                         waiting_reason=reason, hold={'kind': 'blocked', 'reason': reason})
        else:
            state['review'] = review_record(base, state, request.get('path'))
            state['final_approval'] = None
            state['phase'] = 'awaiting_final'
    elif action == 'confirm_final':
        require(phase == 'awaiting_final' and state.get('review') and state['review']['basis'] == basis(state),
                'Final human gate opens only after the independent AI review passes')
        require(nonempty(request.get('message_ref')), 'Supply the actual final-result confirmation; silence is not confirmation')
        check_markdown(state, base)
        state['final_approval'] = {
            'message_ref': request['message_ref'],
            'review_sha256': state['review']['receipt']['sha256'],
            'legacy': False,
        }
    elif action == 'finish':
        require(phase == 'awaiting_final' and state.get('review') and state['review']['basis'] == basis(state),
                'Fresh independent review required')
        approval = state.get('final_approval')
        require(isinstance(approval, dict) and not approval.get('legacy')
                and approval.get('review_sha256') == state['review']['receipt']['sha256']
                and nonempty(approval.get('message_ref')),
                'Final human confirmation is required before finish')
        state['review'] = review_record(base, state, state['review']['receipt']['path'])
        check_markdown(state, base)
        state['done_artifacts'] = done_gate(state, base, request.get('artifacts'))
        state['phase'] = 'done'
    elif action == 'rollback':
        require(not state.get('hold'), 'Resolve existing execution hold before rollback')
        require(request.get('to') in {'intake', 'produce', 'review'} and nonempty(request.get('reason')),
                'Rollback needs target and affected scope/reason')
        target = request['to']
        require(target == 'intake' or approved(state), 'Cannot bypass confirmation by rollback')
        require(target != 'review' or state['draft'], 'No draft to review')
        require(not state['impact_pending'] or target == 'intake', 'Assess source impact first')
        state.update(phase=target, review=None, final_approval=None, waiting_reason=None, resume_phase=None)
        if target == 'intake':
            state['approval'] = None
            state['goal_review'] = None
    elif action == 'pause':
        require(phase not in {'blocked', 'failed', 'done'} and request.get('kind') in {'blocked', 'failed'}
                and nonempty(request.get('reason')), 'Invalid pause')
        state.update(phase=request['kind'], resume_phase=phase, waiting_reason=request['reason'],
                     hold={'kind': request['kind'], 'reason': request['reason']})
    elif action == 'resume':
        require(phase in {'blocked', 'failed'} and not state['impact_pending'] and nonempty(request.get('reason')),
                'Resume needs resolved blocker/failure; reassess changed sources first')
        state.update(phase=state['resume_phase'], resume_phase=None, waiting_reason=None, hold=None)
    elif action == 'set_sources':
        require(nonempty(request.get('reason')), 'Source list change needs a reason')
        state.update(sources=artifacts(base, request.get('paths')), review=None, final_approval=None, impact_pending=True,
                     phase='blocked', resume_phase='produce' if approved(state) else 'goal_review',
                     waiting_reason='Source inventory changed; assess impact before proceeding')
        preserve_hold(state)
    elif action == 'reassess':
        require(state['impact_pending'] and isinstance(request.get('requirements_changed'), bool)
                and nonempty(request.get('reason')), 'Source reassessment needs impact and evidence-based reason')
        state.update(impact_pending=False, review=None, final_approval=None, waiting_reason=None, resume_phase=None)
        if request['requirements_changed']:
            state.update(phase='intake', approval=None, goal_review=None)
        else:
            state['phase'] = 'produce' if approved(state) else 'goal_review'
        preserve_hold(state)
    else:
        raise GuardError('Unknown action')
    event(state, action, {k: v for k, v in request.items() if k != 'action'})


def public_view(state):
    return {
        'ok': True,
        'schema': state['schema'],
        'phase': state['phase'],
        'waiting_reason': state['waiting_reason'],
        'basis': basis(state),
        'task_type': state['task_type'],
        'execution_required': state['execution_required'],
        'require_materials_map': state['require_materials_map'],
        'materials_map': state['materials_map'],
        'goal_review_passed': goal_passed(state),
        'final_approval': state['final_approval'],
        'segments': state['segments'],
        'plan_frozen': bool(state['plan'] and state['plan'].get('frozen')),
        'stage_started_at': state['stage_started_at'],
        'done_artifacts': state['done_artifacts'],
        'steps_completed': sorted(state['step_records']),
        'evidence_binder_ok': bool(state['evidence_binder'] and state['evidence_binder'].get('status') == 'ok'),
        'notes_allowed': state['notes_allowed'],
        'progress': state['progress'],
    }


def transact(path, request):
    path = Path(path).resolve()
    require(isinstance(request, dict), 'Request must be an object')
    if request.get('action') == 'init':
        require(not path.exists(), 'State already exists; never silently reset')
        require(nonempty(request.get('maker')), 'Maker identity required')
        execution_required, task_type = resolve_execution(request)
        require_materials_map = request.get('require_materials_map', True)
        require(isinstance(require_materials_map, bool), 'require_materials_map must be true or false')
        state = dict(schema=3, phase='intake', maker=request['maker'], task_type=task_type,
                     sources=artifacts(path.parent, request.get('sources', [])),
                     intention=None, draft=[], evidence=[], approval=None, review=None, impact_pending=False,
                     waiting_reason=None, resume_phase=None, hold=None, events=[],
                     execution_required=execution_required, require_materials_map=require_materials_map,
                     materials_map=None, stage_started_at=utc_stamp(), done_artifacts=[])
        gate_defaults(state)
        plan_defaults(state, execution_required, require_materials_map)
        event(state, 'init', 'Initialized; task_type=' + task_type
              + '; execution_required=' + str(execution_required) + '; no user approval implied')
    else:
        state = read_json(path)
        require(isinstance(state, dict), 'State must be an object')
        if state.get('schema') in {1, 2}:
            original_schema = state.get('schema')
            original = path.read_bytes()
            require(state.get('phase') in PHASES and nonempty(state.get('maker')), 'Invalid phase/maker')
            upgrade(state)
            plan_defaults(state)
            stage_defaults(state)
            gate_defaults(state)
            validate(state)
            backup = path.with_suffix(path.suffix + '.schema' + str(original_schema) + '.bak')
            if not backup.exists():
                with open(backup, 'xb') as stream:
                    stream.write(original)
                    stream.flush()
                    os.fsync(stream.fileno())
        elif state.get('schema') != 3:
            raise GuardError('Unsupported state schema')
        plan_defaults(state)
        stage_defaults(state)
        gate_defaults(state)
        validate(state)
        changed = [] if request.get('action') == 'set_sources' else reconcile(state)
        if changed:
            write_progress(path.parent, state, request)
            atomic_write(path, state)
            require(request.get('action') in {'status', 'reassess', 'rollback'},
                    'Artifacts changed; inspect status and affected work first')
    if request.get('action') != 'init':
        apply(state, request, path.parent)
    validate(state)
    write_progress(path.parent, state, request)
    # Progress is part of the state snapshot so a reader sees the same lists the file shows.
    atomic_write(path, state)
    return state


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True)
    parser.add_argument('--request', required=True, help='UTF-8 JSON action file')
    args = parser.parse_args()
    try:
        state = transact(args.state, read_json(args.request))
        print(json.dumps(public_view(state), ensure_ascii=False))
        return 0
    except (GuardError, OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
