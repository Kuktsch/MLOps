"""Reject stale upstream evaluations and divergence between eval and serving."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from hw67_import import read, validate_upstream, verify_answers
from vendor.hw67_contract import fingerprint

EVIDENCE = Path(__file__).resolve().parents[1]/'evidence/model-synced'


class HW67ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.snapshot = Path(self.temp.name)/'hw67'
        shutil.copytree(EVIDENCE/'hw67-original', self.snapshot)

    def test_complete_upstream_is_recomputed(self):
        result = validate_upstream(self.snapshot, EVIDENCE)
        self.assertEqual(result['scores']['baseline']['n'], 54)
        self.assertEqual(result['scores']['candidate']['valid'], 54)
        self.assertEqual(result['decision']['passed'], False)
        self.assertEqual(result['evaluation_run_id'],
                         read(self.snapshot/'baseline-eval.json')['evaluation_run_id'])

    def test_config_change_requires_new_upstream_evaluation(self):
        path = self.snapshot/'params.json'
        config = read(path)
        config['max_new_tokens'] += 1
        path.write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError, 'Stale HW6–7 evaluation'):
            validate_upstream(self.snapshot, EVIDENCE)

    def test_rehashed_answers_cannot_reuse_upstream_scores(self):
        outputs = read(self.snapshot/'candidate-outputs.json')
        outputs[0]['raw'] = '{"answer":"B"}'
        (self.snapshot/'candidate-outputs.json').write_text(json.dumps(outputs))
        report = read(self.snapshot/'candidate-eval.json')
        report['outputs_sha256'] = fingerprint(outputs)
        (self.snapshot/'candidate-eval.json').write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, 'scores do not match raw'):
            validate_upstream(self.snapshot, EVIDENCE)

    def test_forged_upstream_pass_is_rejected(self):
        (self.snapshot/'quality-gate.json').write_text('{"passed":true}')
        with self.assertRaisesRegex(ValueError, 'Stale HW6–7 gate'):
            validate_upstream(self.snapshot, EVIDENCE)

    def test_changed_upstream_scoring_rule_is_rejected(self):
        path = self.snapshot/'evaluation/solution.py'
        path.write_text(path.read_text()+'\n')
        with self.assertRaisesRegex(ValueError, 'scoring code differs'):
            validate_upstream(self.snapshot, EVIDENCE)

    def test_serving_answers_must_match_imported_evaluation(self):
        outputs = read(self.snapshot/'baseline-outputs.json')
        verify_answers(self.snapshot, 'baseline', outputs)
        outputs[0]['raw'] = '{"answer":"B"}'
        with self.assertRaisesRegex(ValueError, 'Serving answers differ'):
            verify_answers(self.snapshot, 'baseline', outputs)
