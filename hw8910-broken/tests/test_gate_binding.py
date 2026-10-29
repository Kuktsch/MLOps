"""Verify stored full evidence without loading weights or importing ML packages."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from gate import verify_decision
from release import file_digest

PROJECT=Path(__file__).resolve().parents[1]


class GateBindingTests(unittest.TestCase):
    def setUp(self):
        self.root=PROJECT/'.real'  # A resolution anchor only; this directory need not exist.
        self.manifest=json.loads((PROJECT/'evidence/model/manifest-candidate.json').read_text())
        self.report=json.loads((PROJECT/'evidence/model/release-report.json').read_text())

    def test_real_refusal_is_recomputed_from_full_reports(self):
        self.assertIs(verify_decision(self.manifest,self.report,self.root),False)
        self.assertEqual(self.report['candidate_gate']['reason'],'Общая регрессия accuracy')

    def test_manually_forged_pass_is_rejected(self):
        self.report['passed']=True
        with self.assertRaisesRegex(ValueError,'recomputed gate'):
            verify_decision(self.manifest,self.report,self.root)

    def test_rehashed_raw_answers_cannot_reuse_old_scores(self):
        reference=self.report['sources']['candidate_outputs']
        source=(self.root/reference['uri']).resolve()
        outputs=json.loads(source.read_text())
        outputs[0]['raw']='{"answer":"A"}'
        with tempfile.TemporaryDirectory() as directory:
            changed=Path(directory)/'changed-outputs.json'
            changed.write_text(json.dumps(outputs))
            reference.update(uri=str(changed),sha256=file_digest(changed))
            with self.assertRaisesRegex(ValueError,'Scores do not match'):
                verify_decision(self.manifest,self.report,self.root)

    def test_incomplete_source_report_remains_rejected_after_rehash(self):
        reference=self.report['sources']['candidate_eval']
        report=json.loads((self.root/reference['uri']).resolve().read_text())
        report['status']='running'
        with tempfile.TemporaryDirectory() as directory:
            changed=Path(directory)/'incomplete.json'
            changed.write_text(json.dumps(report))
            reference.update(uri=str(changed),sha256=file_digest(changed))
            with self.assertRaisesRegex(ValueError,'Incomplete source'):
                verify_decision(self.manifest,self.report,self.root)
