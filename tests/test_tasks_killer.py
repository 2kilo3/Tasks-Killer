"""Contracts added with the tasks-killer split."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'scripts' / 'workflow_state.py'
spec = importlib.util.spec_from_file_location('workflow_state_tasks', STATE)
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


class TaskTypeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / 'state.json'
        (self.root / '意图.md').write_text('goal', encoding='utf-8')

    def test_task_type_selects_the_execution_gate(self):
        writing = w.transact(self.state, dict(action='init', maker='maker', task_type='writing',
                                              require_materials_map=False, sources=[]))
        self.assertFalse(writing['execution_required'])
        self.state.unlink()
        lab = w.transact(self.state, dict(action='init', maker='maker', task_type='lab',
                                          require_materials_map=False, sources=[]))
        self.assertTrue(lab['execution_required'])
        self.state.unlink()
        overridden = w.transact(self.state, dict(action='init', maker='maker', task_type='lab',
                                                 execution_required=False, require_materials_map=False, sources=[]))
        self.assertFalse(overridden['execution_required'])


class GateAndProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / 'state.json'
        for name in ('意图.md', 'out.txt'):
            (self.root / name).write_text('synthetic ' + name, encoding='utf-8')
        self.call('init', maker='maker-session', task_type='writing', require_materials_map=False, sources=[])

    def call(self, action, **kwargs):
        return w.transact(self.state, dict(action=action, **kwargs))

    def test_goal_rework_does_not_open_the_human_gate(self):
        self.call('submit_intention', path='意图.md')
        receipt = dict(reviewer='goal-reviewer', context_ref='synthetic:goal', target='goal', verdict='rework',
                       intention_sha256=self.call('status')['intention']['sha256'],
                       findings=[{'item': 'scope', 'status': 'fail', 'reason': 'Missing acceptance'}])
        (self.root / 'goal-review.json').write_text(json.dumps(receipt), encoding='utf-8')
        state = self.call('record_goal_review', path='goal-review.json')
        self.assertEqual(state['phase'], 'goal_review')
        with self.assertRaises(w.GuardError):
            self.call('confirm', message_ref='synthetic:should-not-open')

    def test_progress_contract_and_markdown_gate(self):
        text = (self.root / 'progress' / 'STATUS.md').read_text(encoding='utf-8')
        self.assertEqual(w.progress_status_ok(text, 'intake'), [])
        self.call('submit_intention', path='意图.md')
        text = (self.root / 'progress' / 'STATUS.md').read_text(encoding='utf-8')
        self.assertEqual(w.progress_status_ok(text, 'goal_review'), [])
        (self.root / 'excuse.md').write_text('not requested', encoding='utf-8')
        with self.assertRaises(w.GuardError) as caught:
            self.call('markdown_gate')
        self.assertIn('excuse.md', str(caught.exception))
        self.call('allow_markdown', path='excuse.md', reason='The task named this file')
        self.assertTrue(self.call('markdown_gate')['phase'] == 'goal_review')

    def test_segments_share_an_exclusive_lock_and_recover(self):
        lock_spec = importlib.util.spec_from_file_location('resource_lock', ROOT / 'scripts' / 'resource_lock.py')
        locks = importlib.util.module_from_spec(lock_spec)
        lock_spec.loader.exec_module(locks)
        self.call('submit_intention', path='意图.md')
        state = self.call('status')
        receipt = dict(reviewer='goal-reviewer', context_ref='synthetic:goal', target='goal', verdict='pass',
                       intention_sha256=state['intention']['sha256'],
                       findings=[{'item': 'scope', 'status': 'pass', 'reason': 'ok'}])
        (self.root / 'goal-review.json').write_text(json.dumps(receipt), encoding='utf-8')
        self.call('record_goal_review', path='goal-review.json')
        self.call('confirm', message_ref='synthetic:goal-ok')
        self.call('register_segments', segments=[
            {'id': 'A', 'exclusive_resource': 'lab-vm', 'depends_on': []},
            {'id': 'B', 'exclusive_resource': 'lab-vm', 'depends_on': []},
        ])
        lock = self.root / 'lab.lock'
        locks.acquire(lock, owner='worker-a')
        self.call('claim_segment', id='A', owner='worker-a', lock_path='lab.lock')
        with self.assertRaises(w.GuardError):
            self.call('claim_segment', id='B', owner='worker-b', lock_path='lab.lock')
        self.call('verify_segment', id='A', owner='worker-a', evidence=['out.txt'])
        locks.release(lock, 'worker-a')
        locks.acquire(lock, owner='worker-b')
        self.call('claim_segment', id='B', owner='worker-b', lock_path='lab.lock')
        locks.release(lock, 'worker-b')
        recovered = self.call('recover_segment', id='B', stale=True, reason='worker exited before verify')
        self.assertEqual(recovered['segments']['B']['status'], 'rework')


class ConstraintAndModelTests(unittest.TestCase):
    def test_repo_constraints_pass(self):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts' / 'constraint_lint.py')],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_added_constraint_fails_a_bad_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rules = root / 'constraints'
            rules.mkdir()
            sample = root / 'sample.py'
            sample.write_text('value = bad()\n', encoding='utf-8')
            added = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts' / 'constraint_lint.py'),
                                    '--root', str(root), '--rules', str(rules), 'add',
                                    '--id', 'no-bad-call', '--paths', 'sample.py',
                                    '--forbid-regex', r'bad\(', '--message', 'bad() is not allowed'],
                                   capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(added.returncode, 0, added.stdout + added.stderr)
            checked = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts' / 'constraint_lint.py'),
                                      '--root', str(root), '--rules', str(rules)],
                                     capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(checked.returncode, 1, checked.stdout + checked.stderr)
            self.assertIn('no-bad-call', checked.stdout)

    def test_formal_model_checker_passes(self):
        spec = importlib.util.spec_from_file_location('check_model', ROOT / 'formal' / 'check_model.py')
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)
        report = checker.check()
        self.assertTrue(report['ok'], json.dumps(report, ensure_ascii=False))
        self.assertGreater(report['configurations'][0]['states'], 10)


if __name__ == '__main__':
    unittest.main()
