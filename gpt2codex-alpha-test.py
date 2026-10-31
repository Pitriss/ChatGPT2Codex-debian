#!/usr/bin/env python3
"""Isolated alpha packaging/release guards. Never install on the host."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
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

    def test_release_requires_both_clean_install_receipts(self):
        artifacts=self.release_fixture();(artifacts/'smoke-devuan.json').unlink()
        with patch.object(alpha,'inspect_deb'):
            with self.assertRaisesRegex(AssertionError,'missing clean installation'):
                alpha.release_index(artifacts,self.base/'release')

    def test_smoke_receipt_must_match_exact_same_deb(self):
        artifacts=self.release_fixture()
        (artifacts/'smoke-devuan.json').write_text(json.dumps({'status':'PASS','sha256':'wrong'}))
        with patch.object(alpha,'inspect_deb'):
            with self.assertRaises(AssertionError):alpha.release_index(artifacts,self.base/'release')

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

    def test_packaging_cmake_rejects_missing_backend(self):
        cp=subprocess.run(['cmake','-S',str(ROOT/'gui'),'-B',str(self.base/'cmake'),'-DG2C_BUILD_KONSOLE=OFF','-DG2C_REQUIRE_ALL_BACKENDS=ON','-DBUILD_TESTING=OFF'],capture_output=True,text=True)
        self.assertNotEqual(cp.returncode,0)
        self.assertIn('Alpha package requires both',cp.stdout+cp.stderr)

    def test_action_pins_and_default_publication_gate(self):
        lock=json.loads((ROOT/'packaging/ci-lock.json').read_text())
        workflow=(ROOT/'.github/workflows/alpha.yml').read_text()
        for repo,value in lock['actions'].items():self.assertIn(repo+'@'+value['commit'],workflow)
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
        for arch,platform in [('amd64','linux/amd64'),('arm64','linux/arm64'),('armhf','linux/arm/v7')]:
            self.assertIn(f'arch: {arch}, platform: {platform}',workflow)
        self.assertEqual(workflow.count('/src/gpt2codex-alpha-container.sh build'),1)
        self.assertIn('distribution: [debian, devuan]',workflow)
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


if __name__=='__main__':unittest.main(verbosity=2)
