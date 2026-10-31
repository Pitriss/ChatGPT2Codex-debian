#!/usr/bin/env python3
"""Offline CI scheduling/cache regressions. No Docker, Git commands or live sessions."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent


def module(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/file)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


ci=module('ci','gpt2codex-ci.py')
packaging=module('packaging_tests','gpt2codex-alpha-test.py')


class CITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ci-unit-',dir=ROOT/'.tmp')
        self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name).resolve()

    def test_docs_only_push_is_quick_and_never_release_validated(self):
        result=ci.plan('push','refs/heads/main',{},['README.md','.ai/ALPHA_PACKAGING.md','docs/usage.txt'])
        self.assertFalse(result['full']);self.assertFalse(result['arm']);self.assertFalse(result['candidate'])

    def test_application_packaging_workflow_and_runtime_config_are_relevant(self):
        for path in ['src/main.rs','gui/main.cpp','tests/fixtures/mock_app_server.py','Cargo.lock','.cargo/config.toml',
                     'debian/control','packaging/ci-lock.json','gpt2codex-alpha-container.sh','.github/workflows/alpha.yml',
                     '.ai/templates/CODEX_GLOBAL.md','.ai/examples/config.toml','CMakeLists.txt','unknown.cfg']:
            with self.subTest(path=path):
                result=ci.plan('push','refs/heads/main',{},[path]);self.assertTrue(result['full'])
                self.assertEqual([r['arch'] for r in result['matrix']['include']],['amd64'])

    def test_unknown_detection_and_malformed_paths_require_full_ci(self):
        for paths in [None,[],['../README.md'],['/README.md'],['docs/../src/main.rs'],[None]]:
            with self.subTest(paths=paths):self.assertTrue(ci.plan('push','refs/heads/main',{},paths)['full'])

    def test_manual_full_ci_keeps_arm_and_devuan_is_opt_in(self):
        for value in [False,'false',True,'true']:
            result=ci.plan('workflow_dispatch','refs/heads/main',{'inputs':{'run_devuan':value}},['README.md'])
            self.assertTrue(result['full']);self.assertTrue(result['arm']);self.assertTrue(result['candidate'])
            self.assertEqual(result['devuan'],value in [True,'true'])
            self.assertEqual([r['arch'] for r in result['matrix']['include']],['amd64','arm64','armhf'])

    def test_release_tag_always_requests_complete_candidate_even_for_docs(self):
        result=ci.plan('push',ci.RELEASE_REF,{},['README.md'])
        self.assertTrue(result['full']);self.assertTrue(result['arm']);self.assertTrue(result['candidate'])
        self.assertFalse(result['devuan'])
        self.assertFalse(result['matrix']['include'][0]['experimental'])
        self.assertTrue(all(row['experimental'] for row in result['matrix']['include'][1:]))

    def test_push_api_completeness_errors_and_renames(self):
        event={'before':'a'*40,'after':'b'*40}
        good={'status':'ahead','files':[{'filename':'README.md'}]}
        self.assertEqual(ci.changed_paths('push',event,'owner/repo',lambda _:good),['README.md'])
        for response in [{'status':'diverged','files':[]},{'status':'ahead','files':[{'filename':'README.md'}]*300},{}]:
            self.assertIsNone(ci.changed_paths('push',event,'owner/repo',lambda _:response))
        def broken(_):raise OSError('synthetic API outage')
        self.assertIsNone(ci.changed_paths('push',event,'owner/repo',broken))
        renamed={'status':'ahead','files':[{'filename':'docs/example.md','status':'renamed','previous_filename':'src/old.rs'}]}
        names=ci.changed_paths('push',event,'owner/repo',lambda _:renamed)
        self.assertTrue(ci.plan('push','refs/heads/main',{},names)['full'])
        self.assertIsNone(ci.changed_paths('push',{'before':'0'*40,'after':'b'*40},'owner/repo',lambda _:good))

    def test_pull_request_pagination_and_head_identity(self):
        event={'number':4,'pull_request':{'head':{'sha':'c'*40},'base':{'sha':'b'*40}}}
        metadata={'head':{'sha':'c'*40},'base':{'sha':'b'*40},'changed_files':101}
        def fetch(path):
            if '/files?' not in path:return metadata
            return [{'filename':'docs/'+str(n)+'.md'} for n in (range(100) if path.endswith('page=1') else [100])]
        self.assertEqual(len(ci.changed_paths('pull_request',event,'owner/repo',fetch)),101)
        metadata['changed_files']=102
        self.assertIsNone(ci.changed_paths('pull_request',event,'owner/repo',fetch))
        metadata['head']['sha']='d'*40
        self.assertIsNone(ci.changed_paths('pull_request',event,'owner/repo',fetch))

    def test_pull_request_and_tag_never_use_trusted_dependency_cache(self):
        self.assertTrue(ci.cache_allowed('push','refs/heads/main','main'))
        self.assertTrue(ci.cache_allowed('workflow_dispatch','refs/heads/main','main'))
        for event,ref in [('pull_request','refs/pull/1/merge'),('pull_request','refs/heads/main'),
                          ('push',ci.RELEASE_REF),('push','refs/heads/feature'),('workflow_dispatch',ci.RELEASE_REF)]:
            self.assertFalse(ci.cache_allowed(event,ref,'main'))
        workflow=(ROOT/'.github/workflows/alpha.yml').read_text()
        self.assertNotIn('pull_request_target:',workflow)
        self.assertNotIn('restore-keys:',workflow)
        guard="(github.event_name == 'push' || github.event_name == 'workflow_dispatch') && github.ref == format('refs/heads/{0}', github.event.repository.default_branch)"
        self.assertEqual(workflow.count(guard),4)
        self.assertEqual(workflow.count('uses: actions/cache/'),4)
        self.assertIn("hashFiles('Cargo.lock', 'packaging/ci-lock.json')",workflow)
        self.assertNotIn('path: ~/.cargo',workflow)

    def test_cache_miss_still_fetches_locked_and_exports_only_archives(self):
        home=self.base/'cargo';cache=self.base/'cache'
        def fetch(args,**kwargs):
            self.assertEqual(args,['cargo','fetch','--locked']);self.assertEqual(kwargs['env']['CARGO_HOME'],str(home))
            p=home/'registry/cache/index-fixture/crate-1.0.crate';p.parent.mkdir(parents=True);p.write_bytes(b'fixture')
        ci.fetch_cargo(home,cache,fetch)
        self.assertEqual((cache/'index-fixture/crate-1.0.crate').read_bytes(),b'fixture')
        self.assertEqual(len(list(cache.rglob('*'))),2)

    def test_rejected_cache_falls_back_to_one_fresh_locked_fetch(self):
        home=self.base/'cargo';cache=self.base/'cache';p=cache/'index-fixture/crate-1.0.crate'
        p.parent.mkdir(parents=True);p.write_bytes(b'corrupt fixture');calls=[]
        def fetch(args,**kwargs):
            calls.append(args)
            if len(calls)==1:raise subprocess.CalledProcessError(1,args)
            self.assertFalse((home/'registry').exists())
            path=home/'registry/cache/index-fixture/crate-1.0.crate';path.parent.mkdir(parents=True);path.write_bytes(b'verified fixture')
        ci.fetch_cargo(home,cache,fetch)
        self.assertEqual(calls,[['cargo','fetch','--locked']]*2)
        self.assertEqual(p.read_bytes(),b'verified fixture')
        self.assertEqual((home/'rejected-registry/cache/index-fixture/crate-1.0.crate').read_bytes(),b'corrupt fixture')

    def test_unavailable_cache_does_not_block_a_cold_fetch(self):
        with patch.object(ci,'copy_archives',side_effect=PermissionError),patch.object(ci.subprocess,'run') as fetch:
            ci.fetch_cargo(self.base/'cargo',self.base/'unavailable',fetch)
        fetch.assert_called_once();self.assertEqual(fetch.call_args.args[0],['cargo','fetch','--locked'])

    def test_cache_never_copies_credentials_sources_or_symlinks(self):
        source=self.base/'cache';dest=self.base/'destination';(source/'index-fixture').mkdir(parents=True)
        (source/'credentials.toml').write_text('synthetic private marker')
        (source/'index-fixture/config.json').write_text('synthetic configuration')
        target=source/'index-fixture/crate-1.0.crate';target.write_bytes(b'archive fixture')
        (source/'index-fixture/linked-1.crate').symlink_to(target)
        self.assertEqual(ci.copy_archives(source,dest),1)
        self.assertEqual([str(p.relative_to(dest)) for p in dest.rglob('*')],['index-fixture','index-fixture/crate-1.0.crate'])

    def test_light_suite_preserves_all_full_tests_and_separates_only_qt(self):
        full={t.id() for t in packaging.packaging_suite()};light={t.id() for t in packaging.packaging_suite(light=True)}
        self.assertEqual(full-light,{'packaging_tests.AlphaTests.test_packaging_cmake_rejects_missing_backend'})
        self.assertTrue(light)
        container=(ROOT/'gpt2codex-alpha-container.sh').read_text()
        self.assertIn('cargo test --frozen --all-targets',container)
        self.assertIn('python3 ./gpt2codex-alpha-test.py\n',container)
        self.assertIn('python3 ./gpt2codex-alpha-test.py --light',container)

    def test_plan_cli_outputs_boolean_and_matrix_values_for_github(self):
        event=self.base/'event.json';event.write_text('{"inputs":{}}');output=self.base/'outputs'
        env={**os.environ,'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_REF':'refs/heads/main','GITHUB_REPOSITORY':'owner/repo','GITHUB_OUTPUT':str(output)}
        cp=subprocess.run(['python3',str(ROOT/'gpt2codex-ci.py'),'plan','--event',str(event)],env=env,capture_output=True,text=True)
        self.assertEqual(cp.returncode,0,cp.stderr)
        values=dict(line.split('=',1) for line in output.read_text().splitlines())
        self.assertEqual(values['full'],'true');self.assertEqual(values['devuan'],'false')
        self.assertEqual(len(json.loads(values['matrix'])['include']),3)

    def test_actionlint_checksum_failure_is_not_bypassed(self):
        with patch.object(ci.urllib.request,'urlopen',return_value=io.BytesIO(b'changed fixture')):
            with self.assertRaisesRegex(AssertionError,'checksum mismatch'):ci.install_actionlint(self.base/'tool')
        self.assertFalse((self.base/'tool').exists())

    def test_malformed_event_cli_falls_back_to_full_ci(self):
        event=self.base/'event.json';event.write_text('invalid fixture');output=self.base/'outputs'
        env={**os.environ,'GITHUB_EVENT_NAME':'push','GITHUB_REF':'refs/heads/main','GITHUB_REPOSITORY':'owner/repo','GITHUB_OUTPUT':str(output)}
        cp=subprocess.run(['python3',str(ROOT/'gpt2codex-ci.py'),'plan','--event',str(event)],env=env,capture_output=True,text=True)
        self.assertEqual(cp.returncode,0,cp.stderr);self.assertIn('full=true',output.read_text())

    def test_fetch_cli_refuses_shared_cargo_home(self):
        cp=subprocess.run(['python3',str(ROOT/'gpt2codex-ci.py'),'fetch-cargo','--cargo-home','/not-an-isolated-cargo-home','--cache',str(self.base/'cache')],capture_output=True,text=True)
        self.assertNotEqual(cp.returncode,0);self.assertIn('non-isolated',cp.stderr)

    def workflow_python(self, job, marker):
        text=(ROOT/'.github/workflows/alpha.yml').read_text().split('\n  '+job+':\n',1)[1]
        text=text.split(marker,1)[1].split("python3 - <<'PY'\n",1)[1].split('\n          PY',1)[0]
        return '\n'.join(line[10:] if line.startswith('          ') else line for line in text.splitlines())

    def test_workflow_summary_distinguishes_quick_scope_and_optional_failures(self):
        script=self.workflow_python('summary','Report actual scope and mandatory result')
        original={**os.environ,'PLAN':'success','QUICK':'success','FULL':'false','ARM':'false','CANDIDATE':'false',
                  'BUILD':'skipped','DEBIAN':'skipped','DEVUAN':'','VALIDATION':'skipped','GITHUB_STEP_SUMMARY':str(self.base/'summary')}
        cp=subprocess.run(['python3','-c',script],env=original,capture_output=True,text=True)
        self.assertEqual(cp.returncode,0,cp.stderr)
        self.assertIn('not a validated release',(self.base/'summary').read_text())
        for validation,expected in [('success',0),('failure',1),('skipped',1)]:
            env={**original,'FULL':'true','ARM':'true','CANDIDATE':'true','BUILD':'failure','DEBIAN':'success','DEVUAN':'FAIL','VALIDATION':validation}
            cp=subprocess.run(['python3','-c',script],env=env,capture_output=True,text=True)
            self.assertEqual(cp.returncode,expected,cp.stderr)
        self.assertIn('Devuan (optional): FAIL',(self.base/'summary').read_text())

    def test_optional_job_reports_failure_until_real_matching_receipt_exists(self):
        script=self.workflow_python('devuan','- id: result')
        work=self.base/'job';work.mkdir();(work/'smoke').mkdir();(work/'input/validated').mkdir(parents=True)
        deb=work/'input/validated/gpt2codex_0.1.0~alpha1_amd64.deb';deb.write_bytes(b'synthetic candidate')
        import hashlib
        for report,expected in [({'status':'FAIL'},'FAIL'),({'status':'PASS','sha256':'wrong'},'FAIL'),
                                ({'status':'PASS','sha256':hashlib.sha256(deb.read_bytes()).hexdigest()},'PASS')]:
            (work/'smoke/smoke-devuan.json').write_text(json.dumps(report));output=work/'output'
            if output.exists():output.unlink()
            cp=subprocess.run(['python3','-c',script],cwd=work,env={**os.environ,'GITHUB_OUTPUT':str(output)},capture_output=True,text=True)
            self.assertEqual(cp.returncode,0,cp.stderr);self.assertEqual(output.read_text(),'status='+expected+'\n')


if __name__=='__main__':unittest.main(verbosity=2)
