"""Bundled skills keep their own links, and the orchestrator does not name them."""
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BundledToolsTests(unittest.TestCase):
    def test_orchestrator_discovers_skills_without_naming_them(self):
        entry = (ROOT / 'SKILL.md').read_text(encoding='utf-8')
        self.assertNotIn('VMware', entry)
        self.assertNotIn('Postman', entry)
        self.assertIn('skills/*/SKILL.md', entry)
        report = ROOT / 'skills' / 'lab-report' / 'SKILL.md'
        self.assertTrue(report.is_file())
        for skill in (ROOT / 'skills').iterdir():
            if not skill.is_dir():
                continue
            text = (skill / 'SKILL.md').read_text(encoding='utf-8')
            for target in re.findall(r'\]\(([^)]+)\)', text):
                if '://' not in target:
                    self.assertTrue((skill / target).is_file(), target)

    def test_relocated_helpers_run_from_another_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            installed = Path(tmp) / '迁移安装 with spaces'
            shutil.copytree(ROOT / 'skills', installed)
            for helper, flag in (
                ('vmware-lab-pair/scripts/lab_probe.py', '--help'),
                ('postman-local-lab/scripts/run_fixture.py', '--self-test'),
                ('lab-report/scripts/docx_style_check.py', '--help'),
            ):
                result = subprocess.run(
                    [sys.executable, '-X', 'utf8', '-B', str(installed / helper), flag],
                    cwd=tmp, capture_output=True, text=True, encoding='utf-8', timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
