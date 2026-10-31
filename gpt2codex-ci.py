#!/usr/bin/env python3
"""Alpha CI planning, static checks and disposable Cargo archive cache. No Git commands."""
import argparse
import ast
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parent
RELEASE_REF = 'refs/tags/v0.1.0-alpha1'


def docs_only(paths):
    if not paths:
        return False
    for name in paths:
        if not isinstance(name,str) or name.startswith('/') or '\\' in name or any(p in {'.','..',''} for p in name.split('/')):
            return False
        path=PurePosixPath(name)
        if name.startswith(('.ai/templates/','.ai/examples/','.github/')):
            return False
        if path.suffix.lower() not in {'.md','.rst','.txt'}:
            return False
        if len(path.parts)==1 and path.suffix.lower()=='.txt' and path.name not in {'README.txt','LICENSE.txt','AUTHORS.txt'}:
            return False
        if not (len(path.parts)==1 or name.startswith(('.ai/','docs/'))):
            return False
    return True


def plan(event_name, ref, event, paths):
    release=event_name=='push' and ref==RELEASE_REF
    manual=event_name=='workflow_dispatch'
    full=release or manual or not docs_only(paths)
    arm=release or manual
    inputs=event.get('inputs') or {}
    devuan=manual and isinstance(inputs,dict) and inputs.get('run_devuan',False) in (True,'true')
    matrix=[{'arch':'amd64','platform':'linux/amd64','experimental':False}]
    if arm:
        matrix += [{'arch':'arm64','platform':'linux/arm64','experimental':True},
                   {'arch':'armhf','platform':'linux/arm/v7','experimental':True}]
    return {'full':full,'arm':arm,'devuan':devuan,'candidate':release or manual,
            'detection':'unknown: full build required' if paths is None else 'complete',
            'changed_files':len(paths) if paths is not None else None,'matrix':{'include':matrix}}


def api_json(path):
    headers={'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'}
    if token:=os.environ.get('GH_TOKEN'):
        headers['Authorization']='Bearer '+token
    with urllib.request.urlopen(urllib.request.Request('https://api.github.com'+path,headers=headers),timeout=20) as response:
        raw=response.read(8*1024*1024+1)
    if len(raw)>8*1024*1024:
        raise ValueError('oversized change response')
    return json.loads(raw)


def file_names(files):
    names=[]
    for item in files:
        names.append(item['filename'])
        if item.get('status')=='renamed':
            names.append(item['previous_filename'])
    if not all(isinstance(n,str) for n in names):
        raise ValueError('invalid filenames')
    return names


def changed_paths(event_name, event, repository, fetch=api_json):
    """Return None whenever API coverage or the event identity is uncertain."""
    try:
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository):
            return None
        base='/repos/'+repository
        if event_name=='push':
            before,after=event['before'],event['after']
            if not all(re.fullmatch(r'[0-9a-f]{40}',s) and s!='0'*40 for s in [before,after]):
                return None
            data=fetch(base+'/compare/'+before+'...'+after+'?per_page=1&page=1')
            files=data['files']
            if data['status'] not in {'ahead','identical'} or len(files)>=300:
                return None  # Compare API truncates the complete file list at 300.
            return file_names(files)
        if event_name=='pull_request':
            number=event['number'];assert type(number) is int and number>0
            endpoint=base+'/pulls/'+str(number)
            metadata=fetch(endpoint)
            expected=event['pull_request']['head']['sha']
            expected_base=event['pull_request']['base']['sha']
            if metadata['head']['sha']!=expected or metadata['base']['sha']!=expected_base or metadata['changed_files']>3000:
                return None
            files=[]
            for page in range(1,31):
                batch=fetch(endpoint+'/files?per_page=100&page='+str(page))
                files.extend(batch)
                if len(batch)<100:
                    break
            current=fetch(endpoint)
            if len(files)!=metadata['changed_files'] or current['head']['sha']!=expected or current['base']['sha']!=expected_base:
                return None
            return file_names(files)
    except (OSError,ValueError,KeyError,TypeError,AssertionError):
        pass  # No response bodies, credentials or exception URLs in CI output.
    return None


def cache_allowed(event_name, ref, default_branch):
    # Workflow repeats this check in trusted GitHub expressions for restore/save.
    return event_name in {'push','workflow_dispatch'} and ref=='refs/heads/'+default_branch


def copy_archives(source, destination):
    """Cache only ordinary .crate archives, never config, credentials or executables."""
    if not source.is_dir() or source.is_symlink() or destination.is_symlink():
        return 0
    count=0
    for p in source.glob('*/*.crate'):
        if p.is_symlink() or p.parent.is_symlink() or not p.is_file() or p.stat().st_size>64*1024*1024:
            continue
        if not re.fullmatch(r'[A-Za-z0-9_.-]+',p.parent.name) or not re.fullmatch(r'[A-Za-z0-9_.+-]+\.crate',p.name):
            continue
        target=destination/p.parent.name/p.name
        if target.is_symlink() or target.parent.is_symlink():
            continue
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(p,target)
        count+=1
    return count


def fetch_cargo(cargo_home, cache, run=subprocess.run):
    # cargo_home is disposable /work/cargo in the container, never ~/.cargo.
    cargo_home.mkdir(parents=True,exist_ok=True)
    registry=cargo_home/'registry'
    archives=registry/'cache'
    try:
        seeded=copy_archives(cache,archives)
    except OSError:
        seeded=1 if archives.exists() else 0
        print('CARGO_CACHE=import unavailable; using disposable Cargo state')
    env={**os.environ,'CARGO_HOME':str(cargo_home)}
    try:
        run(['cargo','fetch','--locked'],env=env,check=True)
    except subprocess.CalledProcessError:
        if not seeded:
            raise
        # Preserve rejected evidence inside this private container, then fetch
        # fresh data with Cargo.lock checksums. Never retry without --locked.
        registry.rename(cargo_home/'rejected-registry')
        print('CARGO_CACHE=rejected; retrying a cold locked fetch')
        run(['cargo','fetch','--locked'],env=env,check=True)
    try:
        copy_archives(archives,cache)
    except OSError:
        print('CARGO_CACHE=export unavailable; build may continue without cache')


def static_checks(actionlint):
    # Reuse the public source allowlist; do not inspect private configuration.
    import importlib.util
    spec=importlib.util.spec_from_file_location('alpha',ROOT/'gpt2codex-alpha.py')
    alpha=importlib.util.module_from_spec(spec);spec.loader.exec_module(alpha)
    for name in alpha.source_files():
        p=ROOT/name
        if p.suffix=='.py':
            ast.parse(p.read_text(),filename=str(name))
        elif p.suffix=='.sh':
            shell='bash' if 'bash' in p.read_text().splitlines()[0] else 'sh'
            subprocess.run([shell,'-n',str(p)],check=True)
    subprocess.run(['yamllint','-d','{extends: relaxed, rules: {line-length: disable}}',str(ROOT/'.github/workflows')],check=True)
    subprocess.run([str(actionlint),str(ROOT/'.github/workflows/alpha.yml')],check=True)


def install_actionlint(destination):
    lock=json.loads((ROOT/'packaging/ci-lock.json').read_text())['tools']['actionlint']
    with urllib.request.urlopen(lock['url'],timeout=40) as response:
        raw=response.read(32*1024*1024)
    assert hashlib.sha256(raw).hexdigest()==lock['sha256'], 'actionlint checksum mismatch'
    destination.mkdir(parents=True,exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        member=archive.getmember('actionlint')
        assert member.isfile()
        target=destination/'actionlint';target.write_bytes(archive.extractfile(member).read());target.chmod(0o755)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('plan');p.add_argument('--event',type=Path,required=True)
    p=sub.add_parser('fetch-cargo');p.add_argument('--cargo-home',type=Path,required=True);p.add_argument('--cache',type=Path,required=True)
    p=sub.add_parser('static');p.add_argument('--actionlint',type=Path,required=True)
    p=sub.add_parser('actionlint');p.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='plan':
        try:
            event=json.loads(args.event.read_text())
            if not isinstance(event,dict):event={}
        except (OSError,ValueError):event={}
        name=os.environ['GITHUB_EVENT_NAME'];ref=os.environ['GITHUB_REF']
        paths=changed_paths(name,event,os.environ['GITHUB_REPOSITORY']) if name in {'push','pull_request'} and ref!=RELEASE_REF else None
        result=plan(name,ref,event,paths)
        lock=json.loads((ROOT/'packaging/ci-lock.json').read_text())
        result.update({key:lock['images'][key]['image'] for key in ['debian','binfmt']})
        output=Path(os.environ['GITHUB_OUTPUT'])
        with output.open('a') as stream:
            for key,value in result.items():
                stream.write(key+'='+json.dumps(value,separators=(',',':'))+'\n' if not isinstance(value,str) else key+'='+value+'\n')
        print(json.dumps(result,indent=2))
    elif args.command=='fetch-cargo':
        private=(ROOT/'.tmp').resolve()
        container=os.environ.get('G2C_ALPHA_CONTAINER')=='1' and (Path('/.dockerenv').is_file() or Path('/.gpt2codex-alpha-isolated').is_file())
        for path,expected in [(args.cargo_home,Path('/work/cargo')),(args.cache,Path('/cargo-cache'))]:
            assert path.resolve().is_relative_to(private) and path.resolve()!=private or container and path==expected, 'refuse non-isolated Cargo/cache directory'
        fetch_cargo(args.cargo_home,args.cache)
    elif args.command=='static':static_checks(args.actionlint)
    elif args.command=='actionlint':install_actionlint(args.destination)


if __name__=='__main__':main()
