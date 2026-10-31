#!/usr/bin/env python3
"""Isolated alpha packaging/release guards. Never install on the host."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('alpha', ROOT/'gpt2codex-alpha.py')
alpha = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alpha)
spec = importlib.util.spec_from_file_location('infra', ROOT/'gpt2codex-alpha-infra.py')
infra = importlib.util.module_from_spec(spec)
spec.loader.exec_module(infra)


class AlphaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='alpha-unit-',dir=ROOT/'.tmp')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()

    def fixture_source(self):
        root = self.base/'source'
        root.mkdir()
        for p in ['Cargo.toml','Cargo.lock','LICENSE','README.md','AGENTS.md','.gitignore','src/lib.rs','gui/main.cpp','.ai/templates/.project_codex.md']:
            file=root/p;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('public synthetic source\n')
        return root

    def test_candidate_includes_untracked_source_excludes_private_and_cache(self):
        root=self.fixture_source()
        for p in ['.ai/.zzz.handoff-result.md','.ai/.project_codex.md','.ai/CODEX_RESULTS.md','.aws/credentials','target/private','gui/__pycache__/secret.pyc']:
            file=root/p;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('private fixture\n')
        with patch.object(alpha,'ROOT',root),patch.object(alpha,'HELPERS',[]):
            report=alpha.audit()
        names={p['path'] for p in report['files']}
        self.assertIn('src/lib.rs',names);self.assertIn('gui/main.cpp',names)
        self.assertIn('.ai/templates/.project_codex.md',names)
        self.assertNotIn('.ai/.zzz.handoff-result.md',names)
        self.assertNotIn('.ai/CODEX_RESULTS.md',names)
        self.assertFalse(any('credentials' in n or '__pycache__' in n for n in names))
        self.assertEqual(report['findings'],[])

    def test_audit_reports_secret_location_without_value(self):
        root=self.fixture_source()
        secret='ghp_'+'A'*40
        (root/'src/lib.rs').write_text(secret)
        with patch.object(alpha,'ROOT',root),patch.object(alpha,'HELPERS',[]):
            report=alpha.audit()
        self.assertEqual(report['findings'],[{'file':'src/lib.rs','reason':'possible-secret-review-required'}])
        self.assertNotIn(secret,json.dumps(report))

    def test_symlinked_candidate_refused(self):
        root=self.fixture_source()
        (root/'src/link.rs').symlink_to(root/'README.md')
        with patch.object(alpha,'ROOT',root),patch.object(alpha,'HELPERS',[]):
            with self.assertRaises(ValueError):list(alpha.source_files())

    def test_review_exception_is_bound_to_exact_source_hash(self):
        root=self.fixture_source();(root/'packaging').mkdir()
        source=root/'src/lib.rs'
        source.write_text('-----BEGIN '+'OPENSSH PRIVATE KEY-----\nsynthetic fixture\n')
        reviewed={'src/lib.rs':{'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'rule':0}}
        (root/'packaging/reviewed-synthetic-secrets.json').write_text(json.dumps(reviewed))
        with patch.object(alpha,'ROOT',root),patch.object(alpha,'HELPERS',[]):
            self.assertEqual(alpha.audit()['findings'],[])
            source.write_text(source.read_text()+'changed source\n')
            self.assertTrue(alpha.audit()['findings'])

    def test_install_sentinels_detect_changed_state(self):
        with patch.dict(os.environ,{'HOME':str(self.base/'home'),'XDG_STATE_HOME':str(self.base/'state')}):
            (self.base/'home').mkdir()
            alpha.sentinel(self.base/'evidence',True)
            alpha.sentinel(self.base/'evidence',False)
            (self.base/'state/gpt2codex/screen-sessions/screen-fixture.json').write_text('changed')
            with self.assertRaises(AssertionError):alpha.sentinel(self.base/'evidence',False)

    def release_fixture(self):
        artifacts=self.base/'artifacts';artifacts.mkdir()
        package=artifacts/('gpt2codex_'+alpha.VERSION+'_amd64.deb');package.write_bytes(b'synthetic package fixture')
        digest=hashlib.sha256(package.read_bytes()).hexdigest()
        (artifacts/'result-amd64.json').write_text(json.dumps({'status':'PASS','package':package.name,'sha256':digest,'backends':{'konsole':'built-and-tested','qtermwidget':'built-and-tested'}}))
        for distro in ['debian','devuan']:
            (artifacts/('smoke-'+distro+'.json')).write_text(json.dumps({'status':'PASS','sha256':digest}))
        return artifacts

    def test_release_requires_amd64(self):
        artifacts=self.release_fixture();(artifacts/'result-amd64.json').unlink()
        with self.assertRaisesRegex(AssertionError,'mandatory amd64'):
            alpha.release_index(artifacts,self.base/'release')

    def test_experimental_failure_does_not_block_or_publish_package(self):
        artifacts=self.release_fixture()
        (artifacts/'result-armhf.json').write_text(json.dumps({'status':'FAIL','backends':{'konsole':'not verified'}}))
        (artifacts/('gpt2codex_'+alpha.VERSION+'_armhf.deb')).write_bytes(b'unvalidated')
        with patch.object(alpha,'inspect_deb'):
            alpha.release_index(artifacts,self.base/'release')
        self.assertEqual(len(list((self.base/'release').glob('*.deb'))),1)
        self.assertIn('FAIL',(self.base/'release/ARCHITECTURES.md').read_text())

    def test_corrupt_experimental_artifact_does_not_block_amd64(self):
        artifacts=self.release_fixture()
        package=artifacts/('gpt2codex_'+alpha.VERSION+'_arm64.deb');package.write_bytes(b'corrupt')
        for i,report in enumerate([{'status':'PASS','package':package.name,'sha256':'wrong'}, []]):
            (artifacts/'result-arm64.json').write_text(json.dumps(report))
            destination=self.base/('release-'+str(i))
            with patch.object(alpha,'inspect_deb'):
                alpha.release_index(artifacts,destination)
            self.assertEqual(len(list(destination.glob('*.deb'))),1)
            self.assertIn('FAIL (artifact/report validation)',(destination/'ARCHITECTURES.md').read_text())

    def test_release_requires_debian_clean_install_receipt(self):
        artifacts=self.release_fixture();(artifacts/'smoke-debian.json').unlink()
        with patch.object(alpha,'inspect_deb'):
            with self.assertRaisesRegex(AssertionError,'clean installation'):
                alpha.release_index(artifacts,self.base/'release')

    def test_smoke_receipt_must_match_exact_same_deb(self):
        artifacts=self.release_fixture()
        (artifacts/'smoke-debian.json').write_text(json.dumps({'status':'PASS','sha256':'wrong'}))
        with patch.object(alpha,'inspect_deb'):
            with self.assertRaises(AssertionError):alpha.release_index(artifacts,self.base/'release')

    def test_optional_devuan_absence_failure_and_invalid_receipts_do_not_block_debian(self):
        artifacts=self.release_fixture();devuan=artifacts/'smoke-devuan.json'
        variants=[None,{'status':'FAIL'}, {'status':'PASS','sha256':'stale'}, [], 'invalid json']
        for i,value in enumerate(variants):
            if value is None:devuan.unlink()
            else:devuan.write_text(value if isinstance(value,str) else json.dumps(value))
            destination=self.base/('optional-'+str(i))
            with patch.object(alpha,'inspect_deb'):alpha.release_index(artifacts,destination)
            text=(destination/'ARCHITECTURES.md').read_text()
            self.assertIn('Devuan Excalibur (optional): '+('NOT RUN' if value is None else 'FAIL'),text)
            self.assertEqual(len(list(destination.glob('*.deb'))),1)

    def test_duplicate_debian_receipt_refused(self):
        artifacts=self.release_fixture();(artifacts/'duplicate').mkdir()
        (artifacts/'duplicate/smoke-debian.json').write_bytes((artifacts/'smoke-debian.json').read_bytes())
        with patch.object(alpha,'inspect_deb'):
            with self.assertRaisesRegex(AssertionError,'duplicate'):alpha.release_index(artifacts,self.base/'release')

    def test_duplicate_devuan_receipt_is_reported_invalid_without_claiming_pass(self):
        artifacts=self.release_fixture();(artifacts/'duplicate').mkdir()
        (artifacts/'duplicate/smoke-devuan.json').write_bytes((artifacts/'smoke-devuan.json').read_bytes())
        with patch.object(alpha,'inspect_deb'):alpha.release_index(artifacts,self.base/'release')
        self.assertIn('Devuan Excalibur (optional): FAIL',(self.base/'release/ARCHITECTURES.md').read_text())

    def test_incomplete_backend_evidence_refused(self):
        artifacts=self.release_fixture();p=artifacts/'result-amd64.json';data=json.loads(p.read_text())
        data['backends']['konsole']='not built';p.write_text(json.dumps(data))
        with self.assertRaisesRegex(AssertionError,'backend evidence'):alpha.release_index(artifacts,self.base/'release')

    def test_package_checksum_change_refused(self):
        artifacts=self.release_fixture()
        next(artifacts.glob('*.deb')).write_bytes(b'changed')
        with self.assertRaises(AssertionError):alpha.release_index(artifacts,self.base/'release')

    def test_duplicate_arch_report_refused(self):
        artifacts=self.release_fixture();(artifacts/'duplicate').mkdir()
        (artifacts/'duplicate/result-amd64.json').write_bytes((artifacts/'result-amd64.json').read_bytes())
        with self.assertRaisesRegex(AssertionError,'ambiguous'):
            alpha.release_index(artifacts,self.base/'release')

    def test_stale_release_directory_refused(self):
        artifacts=self.release_fixture();destination=self.base/'release';destination.mkdir()
        (destination/'old.deb').write_bytes(b'not approved')
        with self.assertRaisesRegex(AssertionError,'stale release'):
            alpha.release_index(artifacts,destination)

    def test_maintainer_script_refused(self):
        control=io.BytesIO()
        with tarfile.open(fileobj=control,mode='w') as archive:
            member=tarfile.TarInfo('./postinst');member.size=0;archive.addfile(member,io.BytesIO())
        fields='Package: gpt2codex\nVersion: '+alpha.VERSION+'\nArchitecture: amd64\nDepends: screen\nRecommends: konsole-kpart\nSuggests: tmux\n'
        def output(args,**kwargs):return fields if '-f' in args else control.getvalue()
        with patch.object(alpha.subprocess,'check_output',side_effect=output):
            with self.assertRaises(AssertionError):alpha.inspect_deb(Path('fixture.deb'),'amd64')

    def test_systemd_init_dependencies_refused_including_predepends_and_multiarch(self):
        for relation in ['Depends','Pre-Depends']:
            for package in ['systemd','systemd-sysv','systemd:any','systemd-sysv:amd64']:
                with self.subTest(relation=relation,package=package):
                    fields=f'Package: gpt2codex\nVersion: {alpha.VERSION}\nArchitecture: amd64\n{relation}: {package} (>= 1)\n'
                    with patch.object(alpha.subprocess,'check_output',return_value=fields):
                        with self.assertRaisesRegex(AssertionError,'systemd init dependency'):
                            alpha.inspect_deb(Path('fixture.deb'),'amd64')

    def test_inspection_uses_isolated_tmpdir_without_source_tmp(self):
        source=self.base/'src';source.mkdir()
        scratch=self.base/'work/tmp';scratch.mkdir(parents=True)
        package=self.base/'package'
        (package/'DEBIAN').mkdir(parents=True)
        arch=subprocess.check_output(['dpkg','--print-architecture'],text=True).strip()
        (package/'DEBIAN/control').write_text(
            f'Package: gpt2codex\nVersion: {alpha.VERSION}\nArchitecture: {arch}\n'
            'Maintainer: Synthetic fixture\nDescription: inert inspection fixture\n'
            'Depends: screen\nRecommends: konsole-kpart\nSuggests: tmux\n')
        # Native ELF fixtures exercise the real inspector without starting any
        # program or requiring a previously built application package.
        for name in ['usr/bin/gpt2codex','usr/bin/gpt2codex-gui',
                     'usr/lib/fixture/gpt2codex/backends/libgpt2codex-backend-konsole.so',
                     'usr/lib/fixture/gpt2codex/backends/libgpt2codex-backend-qtermwidget.so']:
            target=package/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile('/bin/true',target)
        for name,data in {'usr/share/gpt2codex/backends.json':'{"konsole":true,"qtermwidget":true}',
                          'usr/share/doc/gpt2codex/cargo-licenses/versions.json':'[]'}.items():
            target=package/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(data)
        deb=self.base/'fixture.deb'
        subprocess.run(['dpkg-deb','--build','--root-owner-group',str(package),str(deb)],check=True,capture_output=True)
        with patch.object(alpha,'ROOT',source),patch.dict(os.environ,{'TMPDIR':str(scratch)}),patch.object(alpha,'run',wraps=alpha.run) as extract:
            alpha.inspect_deb(deb,arch)
        unpacked=Path(extract.call_args.args[0][-1])
        self.assertEqual(unpacked.parent,scratch)
        self.assertFalse(unpacked.exists())
        self.assertFalse((source/'.tmp').exists())
        self.assertEqual(list(source.iterdir()),[])

    def smoke_fixture(self, failure='', present=True, distribution='debian'):
        # Run the actual smoke branch with inert command fixtures. Absolute
        # paths are redirected into this test; no installer or GUI is invoked.
        work=self.base/('smoke-'+failure+'-'+str(present));work.mkdir()
        for name in ['work','out','input','lib/fixture/gpt2codex/backends']:
            (work/name).mkdir(parents=True,exist_ok=True)
        for name in ['konsole','qtermwidget']:
            (work/f'lib/fixture/gpt2codex/backends/{name}.so').touch()
        (work/'os-release').write_text('VERSION_ID=13\nVERSION_CODENAME=excalibur\n')
        body=(ROOT/'gpt2codex-alpha-container.sh').read_text().split('elif [ "$mode" = smoke ]; then\n',1)[1].rsplit('\nelse\n',1)[0]
        replacements={'/usr/bin/gpt2codex-gui':'fixture_gui','/etc/os-release':str(work/'os-release'),
                      '/usr/lib/':str(work/'lib')+'/','/work/':str(work/'work')+'/',
                      '/out/':str(work/'out')+'/','/input/':str(work/'input')+'/',
                      'apt-get':'fixture_apt_get','dpkg-query':'fixture_dpkg_query'}
        # Substitute only matches in the original script, never inserted paths.
        body=re.sub('|'.join(map(re.escape,replacements)),lambda match:replacements[match.group(0)],body)
        fixtures=r'''
trace() { printf '%s\n' "$*" >> "$G2C_TRACE"; }
fixture_apt_get() {
    trace "apt-get $*"
    case "$*" in
        --simulate*) test "$G2C_FAIL" != solver ;;
        'purge -y gpt2codex') test "$G2C_FAIL" != purge ;;
    esac
}
dpkg() { if test "$1" = --print-architecture; then printf 'amd64\n'; fi; }
fixture_dpkg_query() { if test "$G2C_PRESENT" = yes; then printf 'systemd\tinstalled\nsystemd-sysv\tinstalled\n'; fi; }
python3() {
    trace "python3 $*"
    case "$*" in
        *' inspect '*) test "$G2C_FAIL" != inspect ;;
        *' self-test '*) test "$G2C_FAIL" != self-test ;;
        *' sentinel '*) case "$*" in *--create*) return 0;; esac; test "$G2C_FAIL" != sentinel ;;
    esac
}
fixture_gui() { if test "$G2C_FAIL" = backend; then printf 'konsole=0 qtermwidget=1\n'; else printf 'konsole=1 qtermwidget=1\n'; fi; }
ldd() { trace "ldd $*"; if test "$G2C_FAIL" = elf; then printf 'library => not found\n'; else printf 'library => fixture\n'; fi; }
'''
        env={**os.environ,'G2C_TRACE':str(work/'trace'),'G2C_FAIL':failure,'G2C_PRESENT':'yes' if present else 'no'}
        cp=subprocess.run(['/bin/sh','-eu','-c',fixtures+body,'fixture','smoke',distribution],env=env,capture_output=True,text=True)
        self.assertTrue((work/'trace').is_file(),cp.stdout+cp.stderr)
        return cp,(work/'trace').read_text(),work

    def test_smoke_allows_present_init_but_checks_dependencies_and_completes_cleanup(self):
        for present in [True,False]:
            with self.subTest(present=present):
                cp,trace,work=self.smoke_fixture(present=present,distribution='debian' if present else 'devuan')
                self.assertEqual(cp.returncode,0,cp.stdout+cp.stderr)
                self.assertIn(' inspect --deb ',trace)
                self.assertIn('systemd- systemd-sysv-',trace)
                self.assertEqual(trace.count('ldd '),4)
                self.assertIn(' self-test ',trace)
                self.assertLess(trace.index('purge -y gpt2codex'),trace.rindex(' sentinel '))
                self.assertTrue((work/'out/init-before.tsv').exists())
                self.assertTrue((work/'out/init-after.tsv').exists())
                self.assertIn('ALPHA_SMOKE_STEP=sentinels',cp.stdout)

    def test_smoke_keeps_inspection_solver_backend_elf_selftest_and_cleanup_guards(self):
        for failure in ['inspect','solver','backend','elf','self-test','purge','sentinel']:
            with self.subTest(failure=failure):
                cp,trace,work=self.smoke_fixture(failure=failure)
                self.assertNotEqual(cp.returncode,0,trace)
                if failure in ['inspect','solver']:
                    self.assertNotIn('apt-get install -y '+str(work/'input'),trace)

    def test_smoke_rewrites_original_paths_only_in_ci_shaped_directory(self):
        # CI stages sources under /work/src. Inserted fixture paths must not
        # themselves match subsequent /work/, /out/ or /input/ substitutions.
        directory=self.base/'work/src/out/input'
        directory.mkdir(parents=True)
        with patch.object(self,'base',directory):
            for present in [True,False]:
                with self.subTest(present=present):
                    cp,trace,work=self.smoke_fixture(present=present,distribution='debian' if present else 'devuan')
                    self.assertEqual(cp.returncode,0,cp.stdout+cp.stderr)
                    self.assertIn('ALPHA_SMOKE_STEP=sentinels',cp.stdout)
                    self.assertIn('apt-get purge -y gpt2codex',trace)

    def test_packaging_cmake_rejects_missing_backend(self):
        cp=subprocess.run(['cmake','-S',str(ROOT/'gui'),'-B',str(self.base/'cmake'),'-DG2C_BUILD_KONSOLE=OFF','-DG2C_REQUIRE_ALL_BACKENDS=ON','-DBUILD_TESTING=OFF'],capture_output=True,text=True)
        self.assertNotEqual(cp.returncode,0)
        self.assertIn('Alpha package requires both',cp.stdout+cp.stderr)

    def test_action_pins_and_default_publication_gate(self):
        lock=json.loads((ROOT/'packaging/ci-lock.json').read_text())
        workflow=(ROOT/'.github/workflows/alpha.yml').read_text()
        for repo,value in lock['actions'].items():
            if repo=='actions/cache':
                for operation in ['restore','save']:self.assertIn(repo+'/'+operation+'@'+value['commit'],workflow)
            else:self.assertIn(repo+'@'+value['commit'],workflow)
        self.assertIn("vars.ALPHA_PUBLISH_ENABLED == 'true'",workflow)
        self.assertIn('environment: alpha-release',workflow)
        self.assertIn('--verify-tag --prerelease',workflow)
        self.assertIn('continue-on-error: ${{ matrix.experimental }}',workflow)
        self.assertIn('fail-fast: false',workflow)

    def test_frozen_apt_includes_security_and_updates_at_locked_date(self):
        # Regression: the base already has security libraries; main alone cannot
        # satisfy the exact-version development dependencies without downgrades.
        script=(ROOT/'gpt2codex-alpha-container.sh').read_text()
        snapshot=json.loads((ROOT/'packaging/ci-lock.json').read_text())['snapshot']
        sources=infra.build_sources(script,self.base/'apt')
        expected=[('debian','trixie'),('debian','trixie-updates'),('debian-security','trixie-security')]
        self.assertEqual(sources.splitlines(),[
            f'deb [check-valid-until=no] http://snapshot.debian.org/archive/{archive}/{snapshot} {suite} main'
            for archive,suite in expected])
        self.assertIn('find /etc/apt/sources.list.d -type f -delete',script)

    def test_all_architectures_share_build_sources_and_smoke_keeps_distro_sources(self):
        workflow=(ROOT/'.github/workflows/alpha.yml').read_text()
        self.assertIn('matrix: ${{ fromJSON(needs.plan.outputs.matrix) }}',workflow)
        self.assertEqual(workflow.count('/src/gpt2codex-alpha-container.sh build'),1)
        for distro in ['debian','devuan']:self.assertIn(' smoke '+distro,workflow)
        self.assertIn('test -f input/validated/gpt2codex_0.1.0~alpha1_amd64.deb',workflow)
        script=(ROOT/'gpt2codex-alpha-container.sh').read_text()
        smoke=script.split('elif [ "$mode" = smoke ]; then',1)[1]
        self.assertNotIn('/etc/apt',smoke)
        self.assertNotIn('snapshot.debian.org',smoke)
        self.assertIn('apt-get install -y "$deb"',smoke)
        # Check executable statements rather than explanatory comments.
        commands='\n'.join(line for line in script.splitlines() if not line.lstrip().startswith('#'))
        for unsafe in ['trusted=yes','allow-unauthenticated','allow-insecure-repositories',
                       'AllowInsecureRepositories','AllowUnauthenticated','--allow-downgrades',
                       '--force-depends','Check-Valid-Until "false"']:
            self.assertNotIn(unsafe,commands)

    def test_oci_apt_reader_checks_layer_hash_and_reads_regular_key_not_alias(self):
        archive=io.BytesIO()
        with tarfile.open(fileobj=archive,mode='w') as tar:
            for name,data in {'var/lib/dpkg/status':b'public package status',
                              'etc/apt/sources.list.d/../../../outside':b'path traversal fixture',
                              'usr/share/keyrings/devuan-archive-keyring.pgp':b'public key fixture'}.items():
                member=tarfile.TarInfo(name);member.size=len(data);tar.addfile(member,io.BytesIO(data))
            alias=tarfile.TarInfo('usr/share/keyrings/devuan-archive-keyring.gpg')
            alias.type=tarfile.SYMTYPE;alias.linkname='devuan-archive-keyring.pgp';tar.addfile(alias)
        layer=archive.getvalue()
        config=b'{"os":"linux","architecture":"amd64"}'
        digest=lambda data:'sha256:'+hashlib.sha256(data).hexdigest()
        manifest=json.dumps({'config':{'digest':digest(config)},'layers':[{'digest':digest(layer)}]}).encode()
        image=digest(manifest)
        lock={'images':{'devuan':{'image':'devuan/devuan@'+image}}}
        responses={'https://auth.docker.io/token?service=registry.docker.io&scope=repository%3Adevuan%2Fdevuan%3Apull':b'{"token":"anonymous fixture"}'}
        base='https://registry-1.docker.io/v2/devuan/devuan/'
        responses.update({base+'manifests/'+image:manifest,base+'blobs/'+digest(config):config,base+'blobs/'+digest(layer):layer})
        with patch.object(infra,'get',side_effect=lambda url,*args:responses[url]):
            files=infra.image_apt_state(lock,'devuan','amd64')
            self.assertEqual(files['usr/share/keyrings/devuan-archive-keyring.pgp'],b'public key fixture')
            self.assertNotIn('usr/share/keyrings/devuan-archive-keyring.gpg',files)
            self.assertNotIn('etc/apt/sources.list.d/../../../outside',files)
            responses[base+'blobs/'+digest(layer)]=b'tampered layer'
            with self.assertRaises(AssertionError):infra.image_apt_state(lock,'devuan','amd64')


def packaging_suite(light=False):
    names=unittest.defaultTestLoader.getTestCaseNames(AlphaTests)
    # Full invocation retains every test. Qt/CMake coverage runs in full CI.
    return unittest.TestSuite(AlphaTests(name) for name in names
                              if not light or name!='test_packaging_cmake_rejects_missing_backend')


if __name__=='__main__':
    if sys.argv[1:]==['--light']:
        print('PACKAGING_SCOPE=light; Qt/CMake coverage belongs to full CI',flush=True)
        sys.exit(not unittest.TextTestRunner(verbosity=2).run(packaging_suite(light=True)).wasSuccessful())
    else:
        unittest.main(verbosity=2)
