"""Produce local release evidence by testing source and an isolated installation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from .paths import PROJECT_ROOT
from .rules_adapter import digest
from .rules_identity import IMPLEMENTATION_ID
from .rules_state import RulesViolation
from .runtime_store import read,write

SCOPE='fixed_pod_host_campaign_dashboard_learning_disabled'
CHECKS={'complete_tests','installed_assets','installed_fingerprint'}


def fingerprint(root=PROJECT_ROOT):
    from .primitive_campaign import CONFIG_FILES,frozen_strategy
    package=Path(__file__).parent
    policies=('AGENT_ARCHITECTURE_V1.md','GAUNTLET_WORKFLOW.md','HOST_RUNTIME.md',
              'HOST_AGENT_POLICY.md','MANUAL_REFEREE_PROTOCOL.md','PRIMITIVE_COORDINATION.md')
    return {'kernel':IMPLEMENTATION_ID,'modules':{p.name:hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(package.glob('*.py'))},
        'web_assets':{p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted((package/'dashboard_static').glob('*')) if p.is_file()},
        'assets':{name:hashlib.sha256((Path(root)/name).read_bytes()).hexdigest()
                  for name in (*CONFIG_FILES,*(f'docs/{p}' for p in policies))},
        'strategy':digest(frozen_strategy(Path(root)))}


def authorized_override(body):
    """Explicit, fingerprint-bound operator waiver; never a passed test receipt."""
    return (body.get('validation_status')=='skipped_by_user_override'
            and body.get('authorization')=="let's just skip the validation - user override"
            and body.get('checks')=={key:False for key in CHECKS}
            and body.get('test_count')==0)


def evidence(root=PROJECT_ROOT):
    path=os.environ.get('EDH_PRIMITIVE_RELEASE_RECEIPT')
    if not path:return None,'No validated release receipt is selected (EDH_PRIMITIVE_RELEASE_RECEIPT)'
    try:
        receipt=read(Path(path),{})
        body=receipt['evidence']
        if receipt['sha256']!=digest(body):return None,'Release receipt checksum changed'
        if (body['schema']!=1 or body['scope']!=SCOPE or body['fingerprint']!=fingerprint(root)
                or (not authorized_override(body) and (body['checks']!={key:True for key in CHECKS}
                or type(body['test_count']) is not int or body['test_count']<1))):return None,'Release evidence does not match the current implementation and scope'
        return receipt,None
    except (OSError,KeyError,TypeError,ValueError):return None,'Release receipt is unreadable or incomplete'


def validate(root,output):
    root=Path(root).resolve();output=Path(output).resolve()
    if output.exists():raise RulesViolation('Use a fresh release receipt path')
    initial=fingerprint(root)
    tests=sorted((root/'tests').glob('test_*.py'))
    if not tests:raise RulesViolation('The complete source test suite is required')
    test_sha=digest({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in tests})
    log=output.with_suffix('.log');log.parent.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ);env.pop('EDH_PRIMITIVE_RELEASE_RECEIPT',None)
    env['PYTHONPATH']=str(root/'src');env['EDH_PROJECT_ROOT']=str(root)
    with log.open('w',encoding='utf8') as stream:
        subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],cwd=root,env=env,
                       stdout=stream,stderr=subprocess.STDOUT,check=True)
    counts=re.findall(r'Ran (\d+) tests? in ',log.read_text(encoding='utf8'))
    if not counts:raise RulesViolation('Missing complete test execution summary')
    with tempfile.TemporaryDirectory(prefix='edh-release-') as directory:
        temp=Path(directory);wheels=temp/'wheels';target=temp/'installed';outside=temp/'outside';outside.mkdir()
        with log.open('a',encoding='utf8') as stream:
            subprocess.run([sys.executable,'-m','pip','wheel','--no-deps','--no-build-isolation','--wheel-dir',str(wheels),str(root)],
                           cwd=outside,stdout=stream,stderr=subprocess.STDOUT,check=True)
            wheel,=wheels.glob('*.whl')
            subprocess.run([sys.executable,'-m','pip','install','--no-deps','--target',str(target),str(wheel)],
                           cwd=outside,stdout=stream,stderr=subprocess.STDOUT,check=True)
            installed=dict(env);installed['EDH_PROJECT_ROOT']=str(target/'share/edh-gauntlet');installed['PYTHONPATH']=str(target)
            subprocess.run([sys.executable,'-m','edh_gauntlet','verify'],cwd=outside,env=installed,
                           stdout=stream,stderr=subprocess.STDOUT,check=True)
            result=subprocess.run([sys.executable,'-c',
                'import json; from edh_gauntlet.primitive_release import fingerprint; print(json.dumps(fingerprint()))'],
                cwd=outside,env=installed,capture_output=True,text=True,check=True)
            if json.loads(result.stdout)!=initial:raise RulesViolation('Installed implementation differs from tested source')
    if (fingerprint(root)!=initial or test_sha!=digest({p.name:hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((root/'tests').glob('test_*.py'))})):
        raise RulesViolation('Source or tests changed during validation; no release receipt published')
    body={'schema':1,'scope':SCOPE,'fingerprint':initial,'test_sources_sha256':test_sha,
          'test_count':int(counts[-1]),'checks':{key:True for key in CHECKS}}
    receipt={'evidence':body,'sha256':digest(body)};write(output,receipt)
    return {'receipt':str(output),'sha256':receipt['sha256'],'test_count':body['test_count']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=PROJECT_ROOT)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(validate(args.root,args.output)))


if __name__=='__main__':main()
