"""Break a disposable code copy, require a real assertion failure, then restore it."""
import difflib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from release import atomic_json,file_digest


def main():
    evidence=PROJECT/'evidence/logs'
    before=file_digest(PROJECT/'release.py')
    with tempfile.TemporaryDirectory(prefix='hw8910-mutation-') as directory:
        root=Path(directory)
        shutil.copyfile(PROJECT/'release.py',root/'release.py')
        shutil.copytree(PROJECT/'tests',root/'tests',ignore=shutil.ignore_patterns('__pycache__'))
        original=(root/'release.py').read_text()
        mutated=original.replace('def validate_release(manifest: dict, report: dict) -> None:\n',
                                'def validate_release(manifest: dict, report: dict) -> None:\n    return  # deliberate broken admission\n',1)
        assert original!=mutated
        (root/'release.py').write_text(mutated)
        (evidence/'intentional-break.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),mutated.splitlines(True),
                                                         fromfile='a/release.py',tofile='b/release.py')))
        try:
            result=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-p','test_release.py','-v'],
                cwd=root,text=True,capture_output=True,timeout=30)
            (evidence/'intentional-break.log').write_text(result.stdout+result.stderr)
            (evidence/'intentional-break.exit').write_text(str(result.returncode)+'\n')
            assert result.returncode!=0 and 'FAIL:' in result.stderr and 'ERROR:' not in result.stderr
            print('BROKEN COPY: exit_code='+str(result.returncode), flush=True)
            print('\n'.join(result.stderr.strip().splitlines()[-4:]), flush=True)
        finally:
            (root/'release.py').write_text(original)
            shutil.rmtree(root/'__pycache__',ignore_errors=True)
        restored=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-p','test_release.py','-v'],
            cwd=root,text=True,capture_output=True,timeout=30)
        (evidence/'restored-code.log').write_text(restored.stdout+restored.stderr)
        assert restored.returncode==0,restored.stderr
        print('RESTORED COPY: exit_code='+str(restored.returncode), flush=True)
        print('\n'.join(restored.stderr.strip().splitlines()[-4:]), flush=True)
        assert before==file_digest(PROJECT/'release.py')
        atomic_json(evidence/'intentional-break.json',{'broken_exit_code':result.returncode,'restored_exit_code':restored.returncode,
            'original_code_unchanged':True,'project_release_sha256':before,'mutation':'validation early return in disposable copy'})
    print('PASS: broken code failed with assertion failures; restored code passed; main source unchanged')


if __name__=='__main__':main()
