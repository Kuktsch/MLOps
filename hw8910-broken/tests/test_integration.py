"""Identical black-box regressions for the preserved prototype and final service.

HW8910_PROJECT selects an implementation. Every command runs from an independent
working directory, never from the source tree. No weights, TestClient or mocks
of HTTP/filesystem/process boundaries are used.
"""
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

PROJECT = Path(os.environ.get('HW8910_PROJECT', Path(__file__).resolve().parents[1])).resolve()
TRACE = os.environ.get('HW8910_TRACE')


def trace(record):
    if TRACE:
        with Path(TRACE).open('a') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class IntegrationHarness:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cwd = Path(self.temp.name)
        self.root = self.cwd / 'workspace'
        self.command('init', expected=0)

    def command(self, *args, expected=None, env=None):
        cmd = [sys.executable, str(PROJECT / 'lab.py'), '--workspace', str(self.root), *args]
        result = subprocess.run(cmd, cwd=self.cwd, text=True, capture_output=True, timeout=30,
                                env={**os.environ, **(env or {})})
        trace({'test': self.id(), 'command': cmd, 'exit_code': result.returncode,
               'stdout': result.stdout, 'stderr': result.stderr})
        if expected is not None:
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def request(self, port, path, payload=None, raw=None):
        data = raw if raw is not None else json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', data=data,
                                     headers={'Content-Type': 'application/json'})
        try:
            response = urllib.request.urlopen(req, timeout=8)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            status, body = response.status, json.loads(response.read())
        trace({'test': self.id(), 'path': path, 'payload': payload, 'status': status, 'body': body})
        return status, body

    @contextmanager
    def server(self, warmup=0):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        with tempfile.TemporaryFile(mode='w+') as log:
            p = subprocess.Popen([sys.executable, str(PROJECT / 'service.py'), '--workspace', str(self.root),
                                  '--port', str(port), '--warmup-seconds', str(warmup)],
                                 cwd=self.cwd, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if p.poll() is not None:
                        log.seek(0)
                        self.fail('Server exited: ' + log.read())
                    try:
                        if self.request(port, '/health')[0] == 200:
                            break
                    except (OSError, ValueError):
                        time.sleep(.025)
                else:
                    self.fail('Server did not start')
                yield port
            finally:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill(); p.wait(timeout=5)
                log.seek(0)
                trace({'test': self.id(), 'server_log': log.read()})

    def wait_ready(self, port):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            status, _ = self.request(port, '/ready')
            _, debug = self.request(port, '/debug')
            if status == 200 and debug['warmup_finished']:
                return
            time.sleep(.03)
        self.fail('Warmup did not finish')

class IntegrationTests(IntegrationHarness, unittest.TestCase):
    def test_process_cache_recovery_and_input_change(self):
        failure = self.command('run', '--fail-after-prepare')
        self.assertNotEqual(failure.returncode, 0)
        self.assertIn('PREPARED', failure.stdout)
        recovered = self.command('run', expected=0)
        self.assertIn('CACHE_HIT', recovered.stdout)
        before = sha(self.root / 'input.txt')
        (self.root / 'input.txt').write_text('Данные изменены по тому же пути\n')
        changed = self.command('run', expected=0)
        self.assertIn('PREPARED', changed.stdout)
        self.assertNotEqual(before, sha(self.root / 'input.txt'))
        config = json.loads((self.root / 'config.json').read_text())
        for key, value in [('tokenizer_revision', 'r2'), ('template_sha256', 'f'*64),
                           ('max_length', 256), ('code_revision', 'prepare-v2')]:
            config[key] = value
            (self.root / 'config.json').write_text(json.dumps(config))
            self.assertIn('PREPARED', self.command('run', expected=0).stdout)

    def test_process_rejection_incomplete_and_foreign_report(self):
        before = sha(self.root / 'accepted.json')
        outcomes = []
        for report in ['report-reject.json', 'report-incomplete.json', 'report-A.json']:
            result = self.command('run', '--report', report)
            outcomes.append((report, result.returncode != 0, before == sha(self.root / 'accepted.json')))
            # Reset only the experimental pointer so each case is independent.
            (self.root / 'accepted.json').write_bytes((self.root / 'manifest-A.json').read_bytes())
            before = sha(self.root / 'accepted.json')
        trace({'test': self.id(), 'rejections': outcomes})
        self.assertTrue(all(rejected and unchanged for _, rejected, unchanged in outcomes), outcomes)

    def test_process_atomic_disk_error_preserves_pointer(self):
        before = sha(self.root / 'accepted.json')
        code = """import json,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
import release
r=Path(sys.argv[2])
m=json.loads((r/'manifest-B.json').read_text());v=json.loads((r/'report-B.json').read_text())
with patch('os.replace',side_effect=OSError('injected replacement failure')):
    release.publish(m,v,r/'accepted.json')
"""
        p = subprocess.run([sys.executable, '-c', code, str(PROJECT), str(self.root)],
                           cwd=self.cwd, text=True, capture_output=True, timeout=10)
        trace({'test': self.id(), 'exit_code': p.returncode, 'stderr': p.stderr,
               'before_sha256': before, 'after_sha256': sha(self.root / 'accepted.json')})
        self.assertNotEqual(p.returncode, 0, 'Replacement error must propagate')
        self.assertEqual(before, sha(self.root / 'accepted.json'))
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_process_repeated_publication_is_one_event(self):
        self.command('run', expected=0)
        before = (self.root / 'accepted.json').read_bytes()
        self.command('run', expected=0)
        self.command('run', expected=0)
        events = [json.loads(s) for s in (self.root / 'publications.jsonl').read_text().splitlines()]
        self.assertEqual(len([e for e in events if e['model_id'] == 'fixture-B']), 1)
        self.assertEqual(before, (self.root / 'accepted.json').read_bytes())

    def test_http_ready_waits_for_warmup(self):
        with self.server(warmup=1.5) as port:
            self.assertEqual(self.request(port, '/health')[0], 200)
            status, _ = self.request(port, '/ready')
            generated, _ = self.request(port, '/generate', {'prompt': 'Тест', 'max_new_tokens': 32})
            self.assertEqual(status, 503)
            self.assertEqual(generated, 503)
            self.wait_ready(port)
            self.assertEqual(self.request(port, '/generate', {'prompt': 'Тест', 'max_new_tokens': 32})[0], 200)
            self.assertEqual(self.request(port, '/debug')[1]['calls'], 1)

    def test_http_loaded_version_restart_and_rollback(self):
        responses = []
        with self.server() as port:
            self.wait_ready(port)
            responses.append(self.request(port, '/generate', {'prompt': 'A'})[1])
            self.command('run', expected=0)
            responses.append(self.request(port, '/generate', {'prompt': 'still A'})[1])
        with self.server() as port:
            self.wait_ready(port)
            responses.append(self.request(port, '/generate', {'prompt': 'B'})[1])
        # Same compatibility operation for the prototype and corrected code.
        code = """import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1]); import release
r=Path(sys.argv[2]);release.publish(json.loads((r/'manifest-A.json').read_text()),json.loads((r/'report-A.json').read_text()),r/'accepted.json')
"""
        subprocess.run([sys.executable, '-c', code, str(PROJECT), str(self.root)],
                       cwd=self.cwd, check=True, timeout=10)
        with self.server() as port:
            self.wait_ready(port)
            responses.append(self.request(port, '/generate', {'prompt': 'A again'})[1])
        for response, expected in zip(responses, ['fixture-A', 'fixture-A', 'fixture-B', 'fixture-A']):
            self.assertEqual(response['model_id'], expected)
            self.assertIn(expected, response['answer'])
            self.assertEqual(response['runtime_sha256'], json.loads((self.root / 'manifest-A.json').read_text())['runtime_sha256'])

    def test_http_bad_request_never_calls_backend(self):
        with self.server() as port:
            self.wait_ready(port)
            before = self.request(port, '/debug')[1]['calls']
            results = []
            for payload in [{'prompt': ''}, {'prompt': '  '}, {'prompt': 'x', 'max_new_tokens': 0},
                            {'prompt': 'x', 'max_new_tokens': 100000}, {'prompt': 'x', 'max_new_tokens': '32'},
                            {'prompt': 'x', 'max_new_tokens': True}, {'prompt': 12}, ['x']]:
                status, _ = self.request(port, '/generate', payload)
                results.append(status)
            after = self.request(port, '/debug')[1]['calls']
            self.assertTrue(all(400 <= s < 500 for s in results), results)
            self.assertEqual(before, after)
            self.assertEqual(self.request(port, '/generate', {'prompt': 'valid'})[0], 200)
            self.assertEqual(self.request(port, '/debug')[1]['calls'], before+1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
