"""Content-addressed source/data baselines, independent of live game state."""
from __future__ import annotations
import argparse,gzip,hashlib,io,json,os,platform,tarfile,tempfile
from pathlib import Path


def digest(value):return hashlib.sha256(value).hexdigest()


def source_files(root):
    root=Path(root).resolve()
    candidates=[root/'pyproject.toml',root/'AGENTS.md']
    for folder,pattern in [('src','*.py'),('tests','*.py'),('tools','*.py'),('.github/workflows','*.yml'),('src/edh_gauntlet/dashboard_static','*'),('docs','*.md'),
                           ('data/catalog','*.json'),('data/rules','*.json'),('data/reference','*'),('data/decks','*'),('data/strategy','*')]:
        candidates.extend((root/folder).rglob(pattern))
    return sorted({p for p in candidates if p.is_file() and not p.is_symlink() and p.name not in {'learning_quarantine.json','quarantine_transaction.json'}})


def capture(root,output):
    root=Path(root).resolve();output=Path(output);paths=source_files(root)
    contents={str(p.relative_to(root)).replace(os.sep,'/'):p.read_bytes() for p in paths}
    if not contents:raise ValueError('No source assets found')
    manifest={'schema':1,'python':platform.python_version(),'files':{name:digest(data) for name,data in contents.items()},
              'scope':'source, rules/card assets and policy; excludes live game data, credentials and private pilot memory'}
    encoded=json.dumps(manifest,sort_keys=True,separators=(',',':')).encode();key=digest(encoded)
    # Abort if concurrent engineering changed any captured source during the read.
    if source_files(root)!=paths or any(p.read_bytes()!=contents[str(p.relative_to(root)).replace(os.sep,'/')] for p in paths):
        raise RuntimeError('Source changed during capture; retry after the writer stops')
    output.mkdir(parents=True,exist_ok=True);target=output/(key+'.tar.gz')
    if target.exists():verify(target);return target
    fd,tmp=tempfile.mkstemp(prefix='.baseline-',dir=output)
    try:
        with os.fdopen(fd,'wb') as raw,gzip.GzipFile(fileobj=raw,mode='wb',mtime=0,filename='') as gz,tarfile.open(fileobj=gz,mode='w') as archive:
            for name,data in [('BASELINE.json',encoded),*contents.items()]:
                info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o644;archive.addfile(info,io.BytesIO(data))
        os.replace(tmp,target)
    finally:
        if Path(tmp).exists():Path(tmp).unlink()
    verify(target);return target


def verify(path):
    path=Path(path)
    with tarfile.open(path,'r:gz') as archive:
        members=archive.getmembers();names=[m.name for m in members]
        if len(set(names))!=len(names) or any(not m.isfile() or m.name.startswith('/') or '..' in Path(m.name).parts for m in members):
            raise ValueError('Unsafe or duplicate baseline member')
        manifest_bytes=archive.extractfile('BASELINE.json').read();manifest=json.loads(manifest_bytes)
        if path.name!=digest(manifest_bytes)+'.tar.gz':raise ValueError('Baseline identity mismatch')
        if set(names)!={'BASELINE.json',*manifest['files']}:raise ValueError('Baseline file set mismatch')
        for name,expected in manifest['files'].items():
            if digest(archive.extractfile(name).read())!=expected:raise ValueError('Baseline content mismatch: '+name)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=Path('.'));parser.add_argument('--output',type=Path,default=Path('archive/rules-baselines'));parser.add_argument('--verify',type=Path)
    args=parser.parse_args()
    if args.verify:print(json.dumps({'verified':str(args.verify),'files':len(verify(args.verify)['files'])}))
    else:
        path=capture(args.root,args.output);print(json.dumps({'baseline':str(path),'files':len(verify(path)['files'])}))


if __name__=='__main__':main()
