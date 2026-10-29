"""Additional crash, integrity and runtime-boundary regressions for final code."""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
import unittest
from test_integration import IntegrationHarness, PROJECT, sha
import release
from artifacts import verify_artifact
from publication import record_release, recover
from rollback import rollback


# Inherit helpers without duplicating the seven red/green test cases.
class RecoveryTests(IntegrationHarness, unittest.TestCase):
    def test_crash_between_pointer_and_event_recovers_once(self):
        failed = self.command('run', '--fail-after-pointer')
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(json.loads((self.root/'accepted.json').read_text())['model_id'], 'fixture-B')
        self.assertIsNotNone(json.loads((self.root/'release-state.json').read_text())['pending'])
        self.assertIn('RECOVERED_PUBLICATION', self.command('run', expected=0).stdout)
        self.command('run', expected=0)
        events = [json.loads(s) for s in (self.root/'publications.jsonl').read_text().splitlines()]
        self.assertEqual(len([e for e in events if e['model_id']=='fixture-B']),1)
        self.assertIsNone(json.loads((self.root/'release-state.json').read_text())['pending'])

    def test_changed_artifact_rejected_before_publication_and_load(self):
        before = sha(self.root/'accepted.json')
        (self.root/'model-B.txt').write_text('tampered artifact')
        self.assertNotEqual(self.command('run').returncode,0)
        self.assertEqual(before,sha(self.root/'accepted.json'))
        (self.root/'model-A.txt').write_text('tampered accepted artifact')
        with self.server() as port:
            import time
            time.sleep(.15)
            self.assertEqual(self.request(port,'/health')[0],200)
            self.assertEqual(self.request(port,'/ready')[0],503)
            self.assertEqual(self.request(port,'/generate',{'prompt':'x'})[0],503)
            self.assertEqual(self.request(port,'/debug')[1]['calls'],0)

    def test_rollback_requires_previously_accepted_release(self):
        events=[json.loads(s) for s in (self.root/'publications.jsonl').read_text().splitlines()]
        original=next(e['release_id'] for e in events if e['model_id']=='fixture-A')
        self.command('run',expected=0)
        rollback(self.root,original)
        self.assertEqual(json.loads((self.root/'accepted.json').read_text())['model_id'],'fixture-A')
        before=sha(self.root/'accepted.json')
        with self.assertRaises(ValueError):rollback(self.root,'f'*64)
        self.assertEqual(before,sha(self.root/'accepted.json'))

    def test_runtime_and_decision_are_part_of_release_identity(self):
        self.command('run',expected=0)
        m=json.loads((self.root/'manifest-B.json').read_text())
        r=json.loads((self.root/'report-B.json').read_text())
        r['evaluation_run_id']='another-complete-evaluation'
        result=record_release(self.root,m,r)
        self.assertTrue(result['new_event'])
        m=copy.deepcopy(m);r=copy.deepcopy(r)
        m['runtime']['dtype']='bfloat16'
        m['runtime_sha256']=release.digest(release.canonical(m['runtime']))
        r['runtime_sha256']=m['runtime_sha256']
        self.assertTrue(record_release(self.root,m,r)['new_event'])
        ids=[e['release_id'] for e in recover(self.root)['events']]
        self.assertEqual(len(ids),len(set(ids)))

    def test_publish_serialization_error_keeps_exact_bytes(self):
        before=(self.root/'accepted.json').read_bytes()
        m=json.loads((self.root/'manifest-B.json').read_text())
        r=json.loads((self.root/'report-B.json').read_text())
        m['extra']=object()
        with self.assertRaises(TypeError):release.publish(m,r,self.root/'accepted.json')
        self.assertEqual(before,(self.root/'accepted.json').read_bytes())


