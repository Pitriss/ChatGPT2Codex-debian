#!/usr/bin/env python3
"""Local alpha staging/audit/inspection and isolated smoke support. No Git writes."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tarfile
import tempfile

VERSION = '0.1.0~alpha1'
ROOT = Path(__file__).resolve().parent
TREES = ['src', 'gui', 'tests', 'debian', 'packaging', '.github', '.ai/templates', '.ai/examples']
AI_DOCS = {'README.md','PROJECT_CONTEXT.md','SECURITY.md','WORKFLOW.md','ARCHITECTURE.md','DECISIONS.md','PLATFORMS_CI.md',
           'P0_CODEX_CLIENT.md','P0_PROJECT_REGISTRY.md','P0_WORKSPACE_MANAGER.md','P0_EXISTING_PROJECTS.md',
           'P0_K2_RULES_MIGRATION.md','P0H_MCP_READONLY.md','P0I_SCREEN_QT6_DESIGN.md','P0J_READONLY_APP_SERVER.md',
           'TMUX_COMPARISON.md','TMUX_LIFECYCLE.md','ALPHA_PACKAGING.md','ALPHA_COMMIT_FILES.md'}
HELPERS = ['gpt2codex-alpha.py', 'gpt2codex-alpha-infra.py', 'gpt2codex-alpha-container.sh',
           'gpt2codex-ci.py', 'gpt2codex-ci-test.py',
           'gpt2codex-alpha-rootfs-test.py',
           'gpt2codex-alpha-test.py', 'gpt2codex-project-icons-test.py', 'gpt2codex-multiplexer-test.py',
           'gpt2codex-terminal-diagnostics.py', 'gpt2codex-p0ic-qt6-test-v2.sh']


def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def source_files():
    paths = [ROOT / p for p in ['Cargo.toml', 'Cargo.lock', 'LICENSE', 'README.md', 'AGENTS.md', '.gitignore'] + HELPERS]
    paths += [p for p in (ROOT / '.ai').glob('*.md') if p.name in AI_DOCS]
    for tree in TREES:
        if (ROOT / tree).exists():
            paths += [p for p in (ROOT / tree).rglob('*') if p.is_file()]
    selected = sorted(set(paths))
    for p in selected:
        relative = p.relative_to(ROOT)
        if any(part.startswith('.') and part not in {'.ai', '.github', '.gitignore', '.project_codex.md'} for part in relative.parts):
            continue
        if relative.name == '.project_codex.md' and relative.parent != Path('.ai/templates'):
            continue
        if '__pycache__' in relative.parts or p.suffix == '.pyc':
            continue
        if not p.is_file() or p.is_symlink():
            raise ValueError('missing or symlinked source: ' + str(relative))
        yield relative


def audit():
    files = list(source_files())
    findings = []
    patterns = [rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',
                rb'\b(?:ghp|github_pat)_[A-Za-z0-9_]{25,}', rb'\bAKIA[0-9A-Z]{16}\b',
                rb'\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}', rb'(?i)(?:password|access_token|api_key)\s*=\s*["\'][^"\'\n]{16,}["\']']
    review_file = ROOT/'packaging/reviewed-synthetic-secrets.json'
    reviewed = json.loads(review_file.read_text()) if review_file.is_file() else {}
    manifest = []
    for name in files:
        data = (ROOT / name).read_bytes()
        if len(data) > 2 * 1024 * 1024 or b'\0' in data:
            findings.append({'file': str(name), 'reason': 'binary-or-large-source'})
        digest = hashlib.sha256(data).hexdigest()
        exception = reviewed.get(str(name),{})
        if any(re.search(pattern, data) and not (exception.get('sha256') == digest and exception.get('rule') == index)
               for index,pattern in enumerate(patterns)):
            findings.append({'file': str(name), 'reason': 'possible-secret-review-required'})
        if any(part.lower() in {'target', '.tmp', '.log', '.git', '.codex', '.aws', '.ssh', 'node_modules'} for part in name.parts):
            findings.append({'file': str(name), 'reason': 'private-or-generated-path'})
        manifest.append({'path': str(name), 'sha256': digest})
    return {'files': manifest, 'findings': findings, 'scan_scope': 'explicit candidate files only; heuristic scan is not a proof of absence'}


def isolated_env(base):
    for name in ['home', 'config/chatgpt2codex/projects', 'state', 'runtime', 'screens', 'repos/bridge/.git']:
        (base / name).mkdir(parents=True, exist_ok=True, mode=0o700)
    config = base / 'config/chatgpt2codex'
    (config / 'config.toml').write_text('[workspace]\nproject_dir=' + json.dumps(str(base / 'repos')) + '\n')
    (config / 'projects/gpt2codex.toml').write_text("[project]\nid='gpt2codex'\ndirectory='bridge'\n")
    return {'PATH': os.environ.get('PATH', os.defpath), 'HOME': str(base / 'home'),
            'XDG_CONFIG_HOME': str(base / 'config'), 'XDG_STATE_HOME': str(base / 'state'),
            'XDG_RUNTIME_DIR': str(base / 'runtime'), 'SCREENDIR': str(base / 'screens'),
            'SCREENRC': '/dev/null', 'SYSSCREENRC': '/dev/null', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
            'QT_QPA_PLATFORM': 'offscreen', 'QT_QPA_PLATFORMTHEME': 'generic', 'GIT_OPTIONAL_LOCKS': '0'}


def self_test(cli, gui):
    temp_parent = Path(os.environ.get('TMPDIR', ROOT / '.tmp'))
    with tempfile.TemporaryDirectory(prefix='alpha-self-', dir=temp_parent) as temp:
        env = isolated_env(Path(temp).resolve())
        cli, gui = Path(cli).resolve(), Path(gui).resolve()
        for flag in ['--help', '-h']:
            cp = run([cli, flag], env=env, capture_output=True, text=True, timeout=10)
            assert 'Usage:' in cp.stdout + cp.stderr
        assert subprocess.run([cli, '--help', 'unexpected'], env=env, capture_output=True, timeout=10).returncode != 0
        cp = run([gui, '--bridge-cli', cli, '--self-test'], env=env, capture_output=True, text=True, timeout=15)
        assert 'P0IC_GUI=OK' in cp.stdout and 'attached=0 started=0' in cp.stdout
        print('ALPHA_SELF_TEST=PASS attached=0 codex_started=0')


def licenses(destination):
    metadata = json.loads(subprocess.check_output(['cargo', 'metadata', '--frozen', '--format-version', '1'], text=True))
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    summary = []
    for package in metadata['packages']:
        if package['name'] == 'chatgpt2codex':
            continue
        directory = Path(package['manifest_path']).parent
        matches = [p for p in directory.rglob('*') if p.is_file() and not p.is_symlink()
                   and (p.name.upper().startswith(('LICENSE', 'LICENCE', 'COPYING', 'COPYRIGHT')))
                   and p.stat().st_size < 512 * 1024]
        assert matches, 'missing license notices: ' + package['name']
        target = destination / (package['name'] + '-' + package['version'])
        for source in matches:
            out = target / source.relative_to(directory)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, out)
        summary.append({k: package[k] for k in ['name', 'version', 'license', 'checksum'] if k in package})
    sysroot = Path(subprocess.check_output(['rustc', '--print', 'sysroot'], text=True).strip())
    rust_notices = [p for p in [sysroot/'share/doc/rust/COPYRIGHT', sysroot/'share/doc/rust/LICENSE-APACHE',
                   sysroot/'share/doc/rust/LICENSE-MIT', Path('/usr/share/doc/rustc/copyright')] if p.is_file()]
    rust_notices += list((sysroot/'share/doc/rust').glob('COPYRIGHT*.html'))
    rust_notices += [p for p in (sysroot/'share/doc/rust/licenses').rglob('*') if p.is_file() and not p.is_symlink()]
    assert rust_notices, 'Rust toolchain notices unavailable'
    for source in rust_notices:
        relative = source.relative_to(sysroot/'share/doc/rust') if source.is_relative_to(sysroot/'share/doc/rust') else Path('debian-copyright')
        out = destination / 'rust-toolchain' / relative
        out.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source, out)
    (destination / 'versions.json').write_text(json.dumps(summary, indent=2) + '\n')


def inspect_deb(deb, expected_arch):
    fields = subprocess.check_output(['dpkg-deb', '-f', str(deb), 'Package', 'Version', 'Architecture', 'Depends', 'Pre-Depends', 'Recommends', 'Suggests'], text=True)
    assert 'Package: gpt2codex\n' in fields and 'Version: ' + VERSION + '\n' in fields
    assert 'Architecture: ' + expected_arch + '\n' in fields
    assert not re.search(r'(?:^|[ ,|])systemd(?:-sysv)?(?::[a-z0-9-]+)?(?:[ ,|(]|$)', fields), 'systemd init dependency is forbidden'
    assert 'screen' in fields and 'Suggests: tmux' in fields and 'Recommends: konsole-kpart' in fields
    control = subprocess.check_output(['dpkg-deb', '--ctrl-tarfile', str(deb)])
    with tarfile.open(fileobj=io.BytesIO(control)) as archive:
        names = {p.name.removeprefix('./') for p in archive}
        assert not names.intersection({'preinst','postinst','prerm','postrm','config'}), names
    temp_parent = Path(os.environ.get('TMPDIR', ROOT / '.tmp'))
    with tempfile.TemporaryDirectory(prefix='alpha-inspect-', dir=temp_parent) as temp:
        run(['dpkg-deb', '-x', deb, temp])
        unpacked = Path(temp)
        modules = sorted(unpacked.glob('usr/lib/*/gpt2codex/backends/*.so'))
        assert len(modules) == 2 and {p.name for p in modules} == {'libgpt2codex-backend-konsole.so','libgpt2codex-backend-qtermwidget.so'}
        assert json.loads((unpacked/'usr/share/gpt2codex/backends.json').read_text()) == {'konsole':True, 'qtermwidget':True}
        binaries = [unpacked/'usr/bin/gpt2codex', unpacked/'usr/bin/gpt2codex-gui'] + modules
        machines = {'amd64':'Advanced Micro Devices X86-64','arm64':'AArch64','armhf':'ARM'}
        for binary in binaries:
            header = subprocess.check_output(['readelf','-h',str(binary)], text=True)
            assert re.search(r'Machine:\s+' + re.escape(machines[expected_arch]) + r'\s*\n', header), binary
            if expected_arch == 'armhf':
                assert 'hard-float ABI' in header, binary
            dynamic = subprocess.check_output(['readelf','-d',str(binary)], text=True)
            assert not any(('RPATH' in line or 'RUNPATH' in line) for line in dynamic.splitlines()), binary
        paths = [str(p.relative_to(unpacked)) for p in unpacked.rglob('*')]
        assert not any(re.search(r'(^|/)(?:\.git|\.tmp|\.log|\.aws|\.codex|screen-sessions|tmux-sockets)(?:/|$)', p) for p in paths)
        assert not any('/systemd/' in p or '/autostart/' in p or '/cron' in p for p in paths)
        assert (unpacked/'usr/share/doc/gpt2codex/cargo-licenses/versions.json').is_file()
    print('ALPHA_PACKAGE=PASS architecture=' + expected_arch + ' modules=2 maintainer_scripts=0')


def sentinel(directory, create):
    # Metadata-only fixtures at the exact application state layout. The HOME is
    # disposable, and no live server/client or Codex executable is created.
    state = Path(os.environ['XDG_STATE_HOME']) / 'gpt2codex/screen-sessions'
    home = Path(os.environ['HOME'])
    if create:
        directory.mkdir(parents=True)
        (state/'tmux-sockets').mkdir(parents=True)
        (state/'screen-fixture.json').write_text('synthetic existing screen record\n')
        (state/'tmux-fixture.tmux.json').write_text('synthetic existing tmux record\n')
        with socket.socket(socket.AF_UNIX) as sock:
            sock.bind(str(state/'tmux-sockets/fixture.sock'))
        (home/'.gpt2codex-install-sentinel').write_text('preserve existing user files\n')
    objects = [state/'screen-fixture.json', state/'tmux-fixture.tmux.json', state/'tmux-sockets/fixture.sock', home/'.gpt2codex-install-sentinel']
    values = {str(p):{'inode':p.lstat().st_ino,'mode':p.lstat().st_mode,
                     'sha256':hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None} for p in objects}
    record = directory/'sentinel.json'
    if create: record.write_text(json.dumps(values,indent=2)+'\n')
    else: assert json.loads(record.read_text()) == values, 'installation changed fixture state/socket'


def release_index(artifacts, destination):
    assert not destination.exists() or not any(destination.iterdir()), 'refuse stale release assets'
    destination.mkdir(parents=True,exist_ok=True)
    rows, sums, accepted = [], [], {}
    for arch in ['amd64','arm64','armhf']:
        try:
            reports = list(artifacts.rglob('result-'+arch+'.json'))
            assert len(reports) <= 1, 'ambiguous build report'
            report = json.loads(reports[0].read_text()) if reports else {'status':'NOT RUN','backends':{}}
            if report['status'] == 'PASS':
                assert report['backends']=={'konsole':'built-and-tested','qtermwidget':'built-and-tested'}, 'incomplete backend evidence'
                packages = list(artifacts.rglob('gpt2codex_'+VERSION+'_'+arch+'.deb'))
                assert len(packages) == 1 and packages[0].name == report['package']
                digest = hashlib.sha256(packages[0].read_bytes()).hexdigest()
                assert digest == report['sha256']
                inspect_deb(packages[0],arch)
                # A failed experimental copy must not leave a partial *.deb
                # that a later release wildcard could accidentally include.
                pending=destination/(arch+'.pending')
                shutil.copyfile(packages[0],pending)
                pending.rename(destination/packages[0].name)
                sums.append(digest+'  '+packages[0].name)
                accepted[arch] = digest
        except (AssertionError,KeyError,TypeError,ValueError,OSError,subprocess.CalledProcessError):
            if arch == 'amd64': raise
            report={'status':'FAIL (artifact/report validation)','backends':{'validation':'invalid experimental input excluded'}}
        rows.append('| '+arch+' | '+report['status']+' | '+json.dumps(report.get('backends',{}),sort_keys=True)+' |')
    assert 'amd64' in accepted, 'mandatory amd64 not validated'
    reports = list(artifacts.rglob('smoke-debian.json'))
    assert len(reports) == 1, 'missing or duplicate clean installation result: debian'
    report = json.loads(reports[0].read_text())
    assert report['status'] == 'PASS' and report['sha256'] == accepted['amd64']
    devuan='NOT RUN'
    reports=list(artifacts.rglob('smoke-devuan.json'))
    if reports:
        try:
            assert len(reports)==1
            report=json.loads(reports[0].read_text())
            assert report['status']=='PASS' and report['sha256']==accepted['amd64']
            devuan='PASS'
        except (AssertionError,KeyError,TypeError,ValueError,OSError):
            devuan='FAIL (optional receipt invalid, failed or ambiguous)'
    (destination/'SHA256SUMS').write_text('\n'.join(sums)+'\n')
    (destination/'ARCHITECTURES.md').write_text('# Alpha 0.1.0~alpha1\n\n| Architecture | Result | Backends |\n|---|---|---|\n'+'\n'.join(rows)+'\n\nThe same amd64 .deb passed the mandatory Debian 13 install/remove smoke test.\nDevuan Excalibur (optional): '+devuan+'.\nARM builds remain experimental; absent evidence means NOT RUN. No automatic Codex/session recovery.\n')


def local_build(allow_unmanaged_toolchain):
    assert (ROOT/'.tmp').is_dir() and (ROOT/'.log').is_dir(), 'managed workspace required'
    report = audit(); assert not report['findings'], 'candidate scan requires review'
    work=Path(tempfile.mkdtemp(prefix='alpha-build-',dir=ROOT/'.tmp')).resolve()
    logs=Path(tempfile.mkdtemp(prefix='alpha-build-',dir=ROOT/'.log')).resolve()
    source=work/'source';source.mkdir()
    for item in report['files']:
        target=source/item['path'];target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/item['path'],target)
        assert hashlib.sha256(target.read_bytes()).hexdigest()==item['sha256']
    (source/'debian/rules').chmod(0o755)
    for name in ['.tmp','.log']:(source/name).mkdir()
    env=dict(os.environ)
    env.update(isolated_env(work/'environment'))
    env['RUSTUP_HOME']=os.environ.get('RUSTUP_HOME',str(Path.home()/'.rustup'))
    env['CARGO_HOME']=os.environ.get('CARGO_HOME',str(Path.home()/'.cargo'))
    env['TMPDIR']=str(work/'environment/tmp');Path(env['TMPDIR']).mkdir()
    args=['dpkg-buildpackage','-b','-us','-uc']
    if allow_unmanaged_toolchain:args.append('-d')
    print('BUILD_SOURCE='+str(source)+' LOGS='+str(logs),flush=True)
    with (logs/'build.log').open('w') as output:
        cp=subprocess.run(args,cwd=source,env=env,stdout=output,stderr=subprocess.STDOUT)
    assert cp.returncode==0, 'build failed; '+str(logs/'build.log')
    arch=subprocess.check_output(['dpkg','--print-architecture'],text=True).strip()
    deb=work/('gpt2codex_'+VERSION+'_'+arch+'.deb')
    inspect_deb(deb,arch)
    result={'status':'PASS','architecture':arch,'package':str(deb),'sha256':hashlib.sha256(deb.read_bytes()).hexdigest(),
            'source':str(source),'build_log':str(logs/'build.log'),'unmanaged_local_rust_toolchain':allow_unmanaged_toolchain,
            'clean_install_debian':'NOT VERIFIED','clean_install_devuan':'NOT VERIFIED','ci_run':'NOT RUN'}
    (logs/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print('ALPHA_LOCAL_BUILD=PASS DEB='+str(deb),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    a = sub.add_parser('audit'); a.add_argument('--output', type=Path, required=True)
    a = sub.add_parser('stage'); a.add_argument('--destination', type=Path, required=True)
    a = sub.add_parser('self-test'); a.add_argument('--cli', required=True); a.add_argument('--gui', required=True)
    a = sub.add_parser('licenses'); a.add_argument('--destination', required=True)
    a = sub.add_parser('inspect'); a.add_argument('--deb', type=Path, required=True); a.add_argument('--arch', choices=['amd64','arm64','armhf'], required=True)
    a = sub.add_parser('sentinel'); a.add_argument('--directory',type=Path,required=True); a.add_argument('--create',action='store_true')
    a = sub.add_parser('release-index'); a.add_argument('--artifacts',type=Path,required=True); a.add_argument('--destination',type=Path,required=True)
    a = sub.add_parser('build-local'); a.add_argument('--allow-unmanaged-rust-toolchain',action='store_true',help='Local diagnostic build with actual Rust on PATH; skip dpkg build-dependency registration check, NOT runtime dependencies. CI never uses this.')
    args = parser.parse_args()
    if args.command == 'audit':
        report = audit(); args.output.write_text(json.dumps(report, indent=2) + '\n')
        print('CANDIDATE_FILES=' + str(len(report['files'])) + ' FINDINGS=' + str(len(report['findings'])))
        for item in report['findings']: print(item['file'] + ': ' + item['reason'])
        assert not report['findings'], 'candidate scan requires review'
    elif args.command == 'stage':
        assert not args.destination.exists(), 'refuse replacing an existing staging tree'
        report = audit(); assert not report['findings'], 'candidate scan requires review'
        args.destination.mkdir(parents=True)
        for item in report['files']:
            target = args.destination / item['path']; target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT / item['path'], target)
        (args.destination/'debian/rules').chmod(0o755)
        for name in ['.tmp','.log']: (args.destination/name).mkdir()
        print('STAGED=' + str(args.destination.resolve()))
    elif args.command == 'self-test': self_test(args.cli, args.gui)
    elif args.command == 'licenses': licenses(args.destination)
    elif args.command == 'inspect': inspect_deb(args.deb, args.arch)
    elif args.command == 'sentinel': sentinel(args.directory,args.create)
    elif args.command == 'release-index': release_index(args.artifacts,args.destination)
    elif args.command == 'build-local': local_build(args.allow_unmanaged_rust_toolchain)


if __name__ == '__main__':
    main()
