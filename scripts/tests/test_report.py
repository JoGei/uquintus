"""Report truthfulness, configuration identity, future records and portability."""
from html.parser import HTMLParser
import hashlib
import json
import os
from pathlib import Path
import sys
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import report


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets = []

    def handle_starttag(self, tag, attrs):
        self.targets += [value for name, value in attrs if name in ('href', 'src')]


class ReportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.build = self.root / 'build'
        self.build.mkdir()
        (self.root / 'config').mkdir()
        (self.root / 'unit.v').write_text('module unit; endmodule\n')
        self.parameters = {'ISA_E': 0, 'MUA_FORWARDING': 1}
        (self.root / 'config/rv32i.yml').write_text(yaml.safe_dump(self.parameters))

    def run_record(self, identifier='run', *, status='passed', selection='all',
                   seed=1, parameters=None, when=100, component='alu', workload=None):
        path = self.build / 'uquintus-rv32i/verilator' / component / identifier
        path.mkdir(parents=True)
        metadata = {'configuration': str(self.root / 'config/rv32i.yml'),
                    'parameters': {'ISA_E': 0}, 'component': component,
                    'action': 'test', 'test': selection, 'seed': seed,
                    'status': status, 'component_manifest': {'tests': ['arithmetic']},
                    'source_sha256': {'unit.v': hashlib.sha256((self.root / 'unit.v').read_bytes()).hexdigest()}}
        if workload:
            metadata['elf'] = {'sha256': workload}
        (path / 'run.json').write_text(json.dumps(metadata))
        (path / 'config.yml').write_text(yaml.safe_dump(parameters or self.parameters))
        (path / 'results.xml').write_text('<testsuites><testsuite><testcase name="arithmetic" time="0.1"/></testsuite></testsuites>')
        os.utime(path / 'run.json', (when, when))
        return path

    def test_retries_do_not_hide_other_seeds_or_partial_suite_failures(self):
        self.run_record('failed', status='failed', when=10)
        self.run_record('retry', when=20)
        self.run_record('different-seed', status='failed', seed=2, when=30)
        self.run_record('partial', selection='arithmetic', when=40)
        data = report.collect(self.build, self.root)
        latest = [r for r in data['records'] if r['latest']]
        self.assertEqual(len(latest), 3)
        self.assertEqual(report.aggregate(latest), 'failed')
        historical = next(r for r in data['records'] if r['source'].endswith('failed/run.json'))
        self.assertFalse(historical['latest'])

    def test_changed_parameters_and_different_workloads_stay_separate(self):
        self.run_record('first', workload='a')
        self.run_record('other-elf', workload='b')
        self.run_record('other-hardware', parameters={'ISA_E': 1, 'MUA_FORWARDING': 0})
        data = report.collect(self.build, self.root)
        self.assertEqual(len({r['configuration']['id'] for r in data['records']}), 2)
        self.assertEqual(sum(r['latest'] for r in data['records']), 3)
        for r in data['records']:
            self.assertEqual(r['configuration']['name'], 'rv32i')

    def test_current_presets_without_runs_and_old_source_evidence(self):
        self.run_record()
        (self.root / 'unit.v').write_text('changed source\n')
        data = report.collect(self.build, self.root)
        self.assertEqual(data['records'][0]['inputs']['status'], 'changed')
        self.assertEqual(data['records'][0]['inputs']['changed'], ['unit.v'])
        self.assertIsNone(data['records'][0]['revision'])
        (self.root / 'unit.v').unlink()
        self.assertEqual(report.collect(self.build, self.root)['records'][0]['inputs']['status'], 'unknown')
        self.assertEqual(report.aggregate([]), 'not_reported')
        (self.root / 'config/unrun.yml').write_text('ISA_E: 1\n')
        self.assertTrue(any(c['name'] == 'unrun' and c['preset'] for c in
                            report.collect(self.build, self.root)['configurations']))

    def test_passed_metadata_requires_consistent_junit_evidence(self):
        path = self.run_record()
        (path / 'results.xml').unlink()
        record = report.collect(self.build, self.root)['records'][0]
        self.assertEqual(record['status'], 'error')
        self.assertEqual(record['declared_status'], 'passed')
        (path / 'results.xml').write_text('<testsuites><testsuite><testcase name="arithmetic"><failure message="bad"/></testcase></testsuite></testsuites>')
        self.assertEqual(report.collect(self.build, self.root)['records'][0]['status'], 'error')
        (path / 'results.xml').write_text('<testsuites><testsuite><testcase name="wrong"/></testsuite></testsuites>')
        self.assertEqual(report.collect(self.build, self.root)['records'][0]['status'], 'error')

    def test_spike_evidence_is_preserved_and_required_for_differential_pass(self):
        path = self.run_record(component='core_elf')
        metadata = json.loads((path / 'run.json').read_text())
        metadata['reference'] = dict(profile='test', executable_sha256='a'*64)
        metadata['context'] = dict(reference='spike:' + 'a'*64)
        (path / 'run.json').write_text(json.dumps(metadata))
        self.assertEqual(report.collect(self.build, self.root)['records'][0]['status'], 'error')
        (path / 'spike.json').write_text(json.dumps(dict(status='failed', detail='first mismatch')))
        self.assertEqual(report.collect(self.build, self.root)['records'][0]['status'], 'error')
        (path / 'spike.json').write_text(json.dumps(dict(status='passed', compared_instructions=12,
            compared_traps=2, compared_mrets=3,
            profile='test', tool=metadata['reference'])))
        (path / 'spike-debug.cmd').write_text('run 1\nquit\n')
        (path / 'spike.log').write_text('reference observation')
        record = report.collect(self.build, self.root)['records'][0]
        self.assertEqual(record['status'], 'passed')
        self.assertEqual(record['tools']['reference']['profile'], 'test')
        self.assertTrue(any(a['path'] == 'spike.log' for a in record['artifacts']))
        self.assertTrue(any(a['path'] == 'spike-debug.cmd' for a in record['artifacts']))
        metrics={m['name']:m['value'] for m in record['metrics']}
        self.assertEqual((metrics['spike_compared_traps'],metrics['spike_compared_mrets']),(2,3))
        self.assertIn('Spike aaaaaaaa', report.run_table([record]))

    def test_reference_profiles_do_not_replace_each_others_results(self):
        for profile,when in [('v1',1),('v2',2)]:
            path=self.run_record(identifier=profile,when=when)
            metadata=json.loads((path/'run.json').read_text())
            metadata['context']=dict(reference='spike:same-binary',reference_profile=profile)
            (path/'run.json').write_text(json.dumps(metadata))
        self.assertEqual(sum(r['latest'] for r in report.collect(self.build,self.root)['records']),2)

    def test_malformed_records_are_reported_as_collection_issues(self):
        path = self.run_record()
        (path / 'run.json').write_text('{incomplete')
        data = report.collect(self.build, self.root)
        self.assertEqual(data['records'], [])
        self.assertEqual(len(data['issues']), 1)

    def native(self, identifier='synth', context=None, unit='um2', value=120):
        directory = self.build / 'uquintus-rv32i/orfs_sky130' / identifier
        directory.mkdir(parents=True)
        value = {'schema_version': 1, 'kind': 'synthesis', 'status': 'passed',
                 'configuration': {'name': 'rv32i', 'parameters': self.parameters},
                 'component': 'uqu_core', 'target': 'orfs_sky130', 'selection': 'synth',
                 'finished_at': '2026-10-21T12:00:00+00:00',
                 'context': context or {}, 'metrics': [{'name': 'cell_area', 'value': value, 'unit': unit}],
                 'artifacts': ['area.txt']}
        (directory / 'report.json').write_text(json.dumps(value))
        (directory / 'area.txt').write_text('fixture only\n')
        return directory

    def test_future_metrics_preserve_units_context_and_timestamp(self):
        self.native('sky', context={'platform': 'sky130', 'corner': 'tt'})
        self.native('ihp', context={'platform': 'ihp_sg13g2', 'corner': 'tt'})
        data = report.collect(self.build, self.root)
        self.assertEqual(len(data['records']), 2)
        self.assertEqual(sum(r['latest'] for r in data['records']), 2)
        charts = report.metric_charts(data['records'])
        self.assertEqual(charts.count('<section>'), 2)
        self.assertEqual(data['records'][0]['time_basis'], 'producer timestamp')
        self.assertEqual(data['records'][0]['metrics'][0]['unit'], 'um2')
        self.assertEqual(data['records'][0]['inputs']['status'], 'unknown')

    def test_missing_context_does_not_create_performance_comparison(self):
        self.native()
        data = report.collect(self.build, self.root)
        self.assertEqual(report.metric_charts(data['records']), '')
        path = self.native('bad', value=float('nan'))
        self.assertTrue(any('finite numeric' in i['detail'] for i in report.collect(self.build, self.root)['issues']))
        raw = report.read_json(path / 'report.json')
        raw['metrics'] = [{'name': 'area', 'value': 2}]
        (path / 'report.json').write_text(json.dumps(raw))
        self.assertTrue(report.collect(self.build, self.root)['issues'])

    def test_artifacts_must_stay_inside_the_run_directory(self):
        path = self.native()
        raw = report.read_json(path / 'report.json')
        raw['artifacts'] = ['../outside.txt']
        (path / 'report.json').write_text(json.dumps(raw))
        self.assertIn('escapes', report.collect(self.build, self.root)['issues'][0]['detail'])

    def test_site_is_portable_escapes_text_and_omits_large_artifacts(self):
        path = self.run_record(component='alu<script>')
        (path / 'simulation.log').write_text('a' * 200)
        (path / 'rvfi.jsonl').write_text('large raw trace')
        output = self.build / 'report'
        data = report.generate(self.build, output, self.root, artifact_limit=100)
        record = data['records'][0]
        self.assertTrue(all('omitted' in a for a in record['artifacts'] if a['path'] in ('simulation.log', 'rvfi.jsonl')))
        page = (output / 'runs' / f'{record["id"]}.html').read_text()
        self.assertIn('alu&lt;script&gt;', page)
        self.assertNotIn('alu<script>', page)
        self.assertTrue((output / '.nojekyll').exists())
        for source in output.rglob('*.html'):
            links = Links()
            links.feed(source.read_text())
            for target in links.targets:
                url = urlsplit(target)
                self.assertFalse(url.scheme, target)
                self.assertTrue((source.parent / unquote(url.path)).exists(), (source, target))
        report.generate(self.build, output, self.root)
        self.assertEqual(len(report.read_json(output / 'data.json')['records']), 1)

    def test_script_data_is_escaped_and_failed_generation_preserves_previous_site(self):
        self.run_record(component='core', parameters={'value': '</script><script>bad</script>'})
        output = self.build / 'report'
        report.generate(self.build, output, self.root)
        old = (output / 'index.html').read_text()
        comparison = (output / 'configurations.html').read_text()
        self.assertNotIn('</script><script>bad', comparison)
        self.assertIn('\\u003c/script>', comparison)
        with patch.object(report, 'render', side_effect=RuntimeError('render failed')):
            with self.assertRaises(RuntimeError):
                report.generate(self.build, output, self.root)
        self.assertEqual((output / 'index.html').read_text(), old)

    def test_refuses_to_replace_non_report_directory(self):
        output = self.build / 'report'
        output.mkdir()
        (output / 'keep.txt').write_text('user content')
        with self.assertRaisesRegex(ValueError, 'not generated'):
            report.generate(self.build, output, self.root)
        self.assertEqual((output / 'keep.txt').read_text(), 'user content')

    def test_core_configuration_view_excludes_component_only_experiments(self):
        unit = self.run_record('unit', parameters={'unit_only': 1}, component='alu')
        core = self.run_record('core', parameters={'core_experiment': 1}, component='core_elf')
        self.run_record('preset-component', component='alu')
        data = report.generate(self.build, self.build / 'report', self.root)
        unit_config = next(r['configuration'] for r in data['records'] if r['source'].endswith('unit/run.json'))
        core_config = next(r['configuration'] for r in data['records'] if r['source'].endswith('core/run.json'))
        configurations = {c['id']: c for c in data['configurations']}
        self.assertEqual(configurations[unit_config['id']]['scope'], 'component')
        self.assertEqual(configurations[core_config['id']]['scope'], 'core')
        self.assertTrue(any(c['preset'] and c['scope'] == 'core' for c in configurations.values()))
        page = (self.build / 'report/configurations.html').read_text()
        self.assertNotIn(unit_config['id'], page)
        self.assertIn(core_config['id'], page)
        self.assertEqual(len(data['records']), 3)
        unit_run = next(r for r in data['records'] if r['source'].endswith('unit/run.json'))
        self.assertTrue((self.build / 'report/runs' / (unit_run['id'] + '.html')).exists())

    def test_producers_can_mark_custom_core_wrappers_explicitly(self):
        path = self.native()
        raw = report.read_json(path / 'report.json')
        raw.update(component='custom_wrapper', configuration_scope='core',
                   configuration=dict(name='wrapped-core', parameters={'ISA_E': 1}))
        (path / 'report.json').write_text(json.dumps(raw))
        data = report.collect(self.build, self.root)
        self.assertEqual(next(c for c in data['configurations'] if c['name'] == 'wrapped-core')['scope'], 'core')
        raw['configuration_scope'] = 'unknown-scope'
        (path / 'report.json').write_text(json.dumps(raw))
        self.assertIn('configuration_scope', report.collect(self.build, self.root)['issues'][0]['detail'])

    def test_each_page_explains_outcomes_and_input_evidence(self):
        for name, meaning in {**report.OUTCOME_LABELS, **report.INPUT_LABELS}.items():
            self.assertIn(report.esc(meaning), report.badge(name))
        html = report.page('Example', '<p>Body</p>')
        self.assertIn('id="legend"', html)
        self.assertIn('Run outcomes', html)
        self.assertIn('Recorded inputs', html)
        self.assertIn('not a test failure', html)
        self.assertIn('A skipped check is not a pass', html)

    def test_suite_declared_exclusions_are_skipped_evidence_not_passed_cases(self):
        path = self.native()
        raw = report.read_json(path / 'report.json')
        raw.update(kind='test', results_file='suite-results.xml', required_tests=['add'],
                   excluded_tests=[dict(name='ma_data', reason='misaligned access policy')],
                   compiler_info=dict(family='gcc', version='14.2.0'))
        (path / 'report.json').write_text(json.dumps(raw))
        (path / 'suite-results.xml').write_text('<testsuites><testsuite><testcase name="add"/>'
            '<testcase name="ma_data"><skipped message="misaligned access policy"/></testcase></testsuite></testsuites>')
        record = report.collect(self.build, self.root)['records'][0]
        self.assertEqual(record['status'], 'passed')
        self.assertEqual([c['status'] for c in record['cases']], ['passed', 'skipped'])
        self.assertEqual(record['tools']['compiler_info']['family'], 'gcc')
        raw['excluded_tests'] = []
        (path / 'report.json').write_text(json.dumps(raw))
        self.assertEqual(report.collect(self.build, self.root)['records'][0]['status'], 'error')

    @unittest.skipUnless(shutil.which('node'), 'optional Node.js check of interactive controls')
    def test_interactive_filters_and_configuration_comparison(self):
        directory = Path(__file__).resolve().parent
        subprocess.run(['node', str(directory / 'report_view_test.js'),
                        str(directory.parent / 'report_assets/report.js')], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


if __name__ == '__main__':
    unittest.main()
