"""New input bytes cannot inherit an evaluation of the old golden set."""
import json
import subprocess
import sys
from pathlib import Path
PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from release import atomic_json,digest,file_digest


def main():
    root=PROJECT/'.real';target=root/'input.txt';original=target.read_bytes()
    before=file_digest(root/'accepted.json')
    try:
        rows=[json.loads(line) for line in original.decode().splitlines() if line.strip()]
        rows[0]['input']+=' [изменён вход]'
        target.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
        changed=file_digest(target)
        p=subprocess.run([sys.executable,str(PROJECT/'flow.py'),'--workspace',str(root),
            '--manifest','manifest-baseline.json','--report','release-report-baseline.json'],
            cwd=PROJECT,text=True,capture_output=True,timeout=180)
        (PROJECT/'evidence/logs/real-flow-changed-input.log').write_text(p.stdout+p.stderr)
        (PROJECT/'evidence/logs/real-flow-changed-input.exit').write_text(str(p.returncode)+'\n')
        assert p.returncode!=0 and 'Prepared input differs from evaluated golden' in p.stderr
        assert file_digest(root/'accepted.json')==before
    finally:
        target.write_bytes(original)
    atomic_json(PROJECT/'evidence/model/changed-input-refusal.json',{'exit_code':p.returncode,
        'old_input_sha256':digest(original),'changed_input_sha256':changed,'restored_input_sha256':file_digest(target),
        'accepted_before_sha256':before,'accepted_after_sha256':file_digest(root/'accepted.json'),
        'reason':'Prepared input differs from evaluated golden: a new evaluation is required'})
    print('NEW_INPUT_REFUSED; original input and accepted pointer restored/unchanged')


if __name__=='__main__':main()
