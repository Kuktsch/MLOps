"""Run genuine Prefect flows in separate processes and assert their journal evidence."""
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from release import atomic_json, file_digest


def main():
    suffix=uuid.uuid4().hex[:10]
    root=PROJECT/('.lab-flow-'+suffix)
    crash=PROJECT/('.lab-crash-'+suffix)
    if root.exists() or crash.exists():raise FileExistsError('Demo workspaces already exist; choose fresh names')
    records=[]
    def run(label,script,args,workspace,success=True):
        cmd=[sys.executable,str(PROJECT/script),'--workspace',str(workspace),*args]
        p=subprocess.run(cmd,cwd=PROJECT,text=True,capture_output=True,timeout=180)
        log=PROJECT/'evidence/logs'/f'{label}.log'
        log.write_text(p.stdout+p.stderr)
        (log.with_suffix('.exit')).write_text(str(p.returncode)+'\n')
        row={'label':label,'command':cmd,'exit_code':p.returncode,'log':str(log.relative_to(PROJECT))}
        records.append(row)
        print(label,p.returncode,flush=True)
        if (p.returncode==0)!=success:raise AssertionError(row)
        return p.stdout+p.stderr
    run('flow-init','lab.py',['init'],root)
    failed=run('flow-fail-prepare','flow.py',['--fail-after-prepare'],root,False)
    assert 'PREPARATION_STATE=Completed' in failed,failed
    recovered=run('flow-recovery','flow.py',[],root)
    assert 'PREPARATION_STATE=Cached' in recovered,recovered
    repeat=run('flow-repeat','flow.py',[],root)
    assert 'ALREADY_PUBLISHED' in repeat
    (root/'input.txt').write_text('Изменённый вход по прежнему пути\n')
    invalidated=run('flow-change-input','flow.py',[],root)
    assert 'PREPARATION_STATE=Completed' in invalidated and 'PREPARED' in invalidated
    config=json.loads((root/'config.json').read_text());config['max_length']=256
    atomic_json(root/'config.json',config)
    changed=run('flow-change-config','flow.py',[],root)
    assert 'PREPARATION_STATE=Completed' in changed
    for report in ['report-reject.json','report-incomplete.json','report-A.json']:
        before=file_digest(root/'accepted.json')
        run('flow-negative-'+report.removesuffix('.json'),'flow.py',['--report',report],root,False)
        after=file_digest(root/'accepted.json')
        assert before==after
        records[-1].update(before_sha256=before,after_sha256=after)
    run('crash-init','lab.py',['init'],crash)
    run('flow-crash-pointer','flow.py',['--fail-after-pointer'],crash,False)
    state=json.loads((crash/'release-state.json').read_text())
    assert state['pending'] is not None
    fixed=run('flow-crash-recovery','flow.py',[],crash)
    assert 'RECOVERED_PUBLICATION' in fixed
    run('flow-crash-repeat','flow.py',[],crash)
    state=json.loads((crash/'release-state.json').read_text())
    assert sum(e['model_id']=='fixture-B' for e in state['events'])==1
    assert state['pending'] is None
    a=next(e['release_id'] for e in state['events'] if e['model_id']=='fixture-A')
    run('flow-controlled-rollback','rollback.py',['--release-id',a],crash)
    assert json.loads((crash/'accepted.json').read_text())['model_id']=='fixture-A'
    output=PROJECT/'evidence/flow'
    output.mkdir(exist_ok=True)
    for name,workspace in [('preparation',root),('crash',crash)]:
        target=output/name;target.mkdir(exist_ok=True)
        for path in workspace.iterdir():
            if path.is_file():shutil.copyfile(path,target/path.name)
        shutil.copytree(workspace/'releases',target/'releases',dirs_exist_ok=True)
    atomic_json(output/'scenarios.json',records)
    print('FLOW_SCENARIOS_VERIFIED',len(records),flush=True)


if __name__=='__main__':main()
