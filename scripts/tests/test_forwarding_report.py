"""Check Pareto direction, qualification and cross-ISA comparison contracts."""
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('forwarding_report',
    ROOT / 'impl/asic/orfs/explore/forwarding_report.py')
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


class ForwardingReportTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'requires Node for browser-script syntax check')
    def test_embedded_javascript_parses(self):
        script = report.PAGE.split('<script>')[1].split('</script>')[0]
        checked = subprocess.run(['node','-e','new Function(require("fs").readFileSync(0,"utf8"))'],
                                 input=script, text=True, capture_output=True)
        self.assertEqual(checked.returncode,0,checked.stderr)

    @unittest.skipUnless(shutil.which('node'), 'requires Node for interactive report checks')
    def test_overlay_keeps_per_backend_frontiers_and_platform_filter(self):
        rows=[]
        for platform, offset in (('sky130hd',0),('ihp-sg13g2',20)):
            for step in range(2):
                rows.append(dict(id=platform+str(step),platform=platform,isa='RV32IMC',step=step,
                    qualified=True,paths=[],area_um2=10+step+offset,execution_time_ms=10-step+offset,
                    f_max_mhz=40+step,cycles=100,cpi=1,benchmark_status='passed',placement_status='passed'))
        fixture=dict(rows=rows,studies=[],constraints=dict(clock_period_ns=60))
        script=report.PAGE.split('<script>')[1].split('</script>')[0]
        harness=r'''
class Element {
 constructor(){this.value='';this.children=[];this.innerHTML='';this.textContent='';this.attrs={};}
 setAttribute(k,v){this.attrs[k]=v;}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(){this.children=[];}
 querySelectorAll(){return [{value:'RV32IMC'}];}
 addEventListener(){}
}
const elements={};
const document={getElementById(id){return elements[id]||(elements[id]=new Element());},
 createElementNS(ns,tag){const e=new Element();e.tag=tag;return e;},querySelectorAll(){return []}};
document.getElementById('data').textContent=JSON.stringify(FIXTURE);
document.getElementById('metric').value='execution_time_ms';
document.getElementById('metric').selectedOptions=[{textContent:'time'}];
'''.replace('FIXTURE',json.dumps(fixture))
        assertions=r'''
const assert=require('assert');
assert.match(byId('status').textContent,/4 qualified points; 4 on/);
assert.equal(byId('plot').children.filter(e=>e.tag==='polyline').length,2);
assert.equal(byId('plot').children.filter(e=>e.tag==='circle'&&e.attrs['stroke-dasharray']).length,2);
assert.match(byId('rows').innerHTML,/ihp-sg13g2/);
byId('platform').value='ihp-sg13g2';render();
assert.match(byId('status').textContent,/2 qualified points; 2 on/);
assert(!byId('rows').innerHTML.includes('sky130hd'));
'''
        result=subprocess.run(['node'],input=harness+script+assertions,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_minimize_time_maximize_frequency_ties_and_failures(self):
        rows = [dict(id=i, platform='sky130hd', qualified=True, area_um2=a,
                     execution_time_ms=t, f_max_mhz=f)
                for i, (a,t,f) in enumerate(((10,30,10),(20,20,15),(30,25,12),(20,20,15)))]
        rows += [dict(id=4, platform='sky130hd', qualified=False, area_um2=1,
                      execution_time_ms=1, f_max_mhz=100),
                 dict(id=5, platform='sky130hd', qualified=True, area_um2=0,
                      execution_time_ms=1, f_max_mhz=100)]
        self.assertEqual([r['id'] for r in report.frontier(rows)], [0,1,3])
        self.assertEqual([r['id'] for r in report.frontier(rows, 'f_max_mhz', True)], [0,1,3])
        other = dict(rows[2], id=6, platform='ihp-sg13g2')
        self.assertIn(other, report.frontier([*rows, other]))

    def fixture(self, root, name, m):
        directory = root/name
        (directory/'config').mkdir(parents=True)
        (directory/'config/f0.yml').write_text(yaml.safe_dump(dict(ISA_E=0, ISA_M=m, ISA_C=1)))
        context = dict(clock_period_ns=60, sdc_sha256='fixed')
        (directory/'experiment.json').write_text(json.dumps(dict(cases=[dict(name='f0')])))
        bench = dict(status='passed', source_sha256={'src/uquintus/uqu_core.v':'same'},
            context=dict(benchmark=dict(name='coremark',iterations=1,compiler_flags=['-O2'],runtime_sha256=name),
            memory=dict(imem_latency=1,dmem_latency=1), execution_mode='fast',validation_scope='crc',
            family='gcc',version='13.2',abi='ilp32',suite_revision='pin',measurement='start-stop'))
        (root/(name+'-rtl.json')).write_text(json.dumps(bench))
        row=dict(name='f0',step=0,paths=[],platform='sky130hd',qualified=True,area_um2=10+m,
                 execution_time_ms=3-m,benchmark_report=name+'-rtl.json')
        (directory/'summary.json').write_text(json.dumps(dict(context=context,rows=[row])))
        return directory

    def test_merge_separate_isa_elf_policies_and_relative_evidence(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(report,'ROOT',Path(temp)):
            root=Path(temp); output=root/'combined'
            a=self.fixture(root,'imc',1);b=self.fixture(root,'ic',0)
            result=report.collect([a,b],output)
            self.assertEqual([s['isa'] for s in result['studies']],['RV32IMC','RV32IC'])
            self.assertEqual(result['rows'][0]['benchmark_report'],'../imc-rtl.json')
            self.assertTrue(all(r['combined_frontier'] for r in result['rows']))
            self.assertFalse(result['studies'][0]['audited'])
            with self.assertRaisesRegex(ValueError,'duplicate'):
                report.collect([a,a],output)
            p=root/'ic-rtl.json'; bad=json.loads(p.read_text())
            bad['context']['memory']['dmem_latency']=2;p.write_text(json.dumps(bad))
            with self.assertRaisesRegex(ValueError,'workload/compiler/memory'):
                report.collect([a,b],output)

    def test_incompatible_constraints_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(report,'ROOT',Path(temp)):
            root=Path(temp); a=self.fixture(root,'imc',1);b=self.fixture(root,'ic',0)
            p=b/'summary.json';bad=json.loads(p.read_text())
            bad['context']['clock_period_ns']=120;p.write_text(json.dumps(bad))
            with self.assertRaisesRegex(ValueError,'clock/SDC'):
                report.collect([a,b],root/'output')

    def test_old_audit_does_not_qualify_newly_added_backend(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(report,'ROOT',Path(temp)):
            root=Path(temp); directory=self.fixture(root,'imc',1)
            experiment=directory/'experiment.json'
            manifest=json.loads(experiment.read_text())
            manifest['platforms']=['sky130hd'];experiment.write_text(json.dumps(manifest))
            (directory/'audit.json').write_text(json.dumps(dict(status='passed',checked_records=2,
                                                               platforms=dict(sky130hd={}))))
            self.assertTrue(report.collect([directory],root/'output')['studies'][0]['audited'])
            manifest['platforms'].append('ihp-sg13g2');experiment.write_text(json.dumps(manifest))
            self.assertFalse(report.collect([directory],root/'output')['studies'][0]['audited'])

    def test_different_rtl_snapshots_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(report,'ROOT',Path(temp)):
            root=Path(temp); a=self.fixture(root,'imc',1);b=self.fixture(root,'ic',0)
            p=root/'ic-rtl.json';bad=json.loads(p.read_text())
            bad['source_sha256']['src/uquintus/uqu_core.v']='changed';p.write_text(json.dumps(bad))
            with self.assertRaisesRegex(ValueError,'RTL source'):
                report.collect([a,b],root/'output')

    def test_implementation_stages_use_exact_sta_and_separate_cell_scopes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); output=root/'html'; run=root/'run'; run.mkdir()
            mapped=[dict(name='cell_count',value=100),dict(name='cell_area',value=1000),
                    dict(name='estimated_fmax',value=999),dict(name='buffer_count',value=10)]
            placed=[dict(name='cell_count',value=140),dict(name='physical_only_count',value=20),
                    dict(name='cell_area',value=1200),dict(name='buffer_count',value=8),
                    dict(name='placement_violations',value=0)]
            (run/'mapped_metrics.json').write_text(json.dumps(mapped))
            record=dict(metrics=placed,artifacts=['results/3_6_place_repair_timing.odb'])
            (run/'report.json').write_text(json.dumps(record))
            for stage,period in (('mapped_preplacement',20),('placed_pre_cts',25)):
                folder=run/'timing'/stage;folder.mkdir(parents=True)
                timing=dict(stage=stage, metrics=dict(minimum_clock_period=period,estimated_fmax=1000/period,
                    setup_worst_slack=60-period,hold_worst_slack=.1,setup_total_negative_slack=0,
                    slew_violations=0,capacitance_violations=0,fanout_violations=0),
                    paths=dict(full_max=dict(status='timed',startpoint='launch',endpoint='capture'),
                               stage_IF_max=dict(status='timed',slack_ns=30,startpoint='ex',endpoint='if')))
                (folder/'summary.json').write_text(json.dumps(timing))
                (folder/'full_max.rpt').write_text('retained path')
            (run/'results').mkdir();(run/'results/3_6_place_repair_timing.odb').write_bytes(b'checkpoint')
            stages=report.implementation_results(record,run/'report.json',output)
            self.assertEqual(stages['mapped_preplacement']['metrics']['estimated_fmax'],50)
            self.assertEqual(stages['placed_pre_cts']['metrics']['estimated_fmax'],40)
            self.assertEqual(stages['placed_pre_cts']['logical_cells'],120)
            self.assertEqual(stages['placed_pre_cts']['capture_paths']['IF']['slack_ns'],30)
            self.assertEqual(stages['placed_pre_cts']['evidence']['checkpoint'],
                             '../run/results/3_6_place_repair_timing.odb')
            row=dict(isa='RV32IMC',name='f0',step=0,platform='sky130hd',implementation=stages)
            data=dict(rows=[row],constraints=dict(clock_period_ns=60))
            flattened=report.physical_rows(data)[0]
            self.assertEqual(flattened['mapped_logic_cells'],100)
            self.assertEqual(flattened['repaired_logic_cells'],120)
            self.assertEqual(flattened['physical_only_cells'],20)
            output.mkdir();report.write_physical_exports(data,output)
            self.assertIn('repaired_logic_cells',(output/'synthesis-layout.csv').read_text())
            self.assertIn('before CTS/routing',(output/'synthesis-layout.md').read_text())
            self.assertIn('repaired ODB',report.physical_html(data))
            (run/'timing/placed_pre_cts/summary.json').unlink()
            stages=report.implementation_results(record,run/'report.json',output)
            self.assertTrue(stages['mapped_preplacement']['available'])
            self.assertFalse(stages['placed_pre_cts']['available'])

    def test_matched_platform_comparison_and_exports(self):
        sky = dict(isa='RV32IMC', name='f3', step=3, platform='sky130hd', qualified=True,
                   area_um2=400, f_max_mhz=40, execution_time_ms=12)
        ihp = dict(sky, platform='ihp-sg13g2', area_um2=200, f_max_mhz=50, execution_time_ms=9.6)
        failed = dict(ihp, name='failed', qualified=False)
        data = dict(rows=[sky, ihp, failed])
        pair, = report.platform_comparisons(data)
        self.assertEqual(pair['area_um2_change_percent'], -50)
        self.assertEqual(pair['f_max_mhz_change_percent'], 25)
        self.assertAlmostEqual(pair['execution_time_ms_change_percent'], -20)
        with tempfile.TemporaryDirectory() as tmp:
            page = report.comparison_html(data, Path(tmp))
            self.assertIn('separately per platform', page)
            self.assertIn('ihp-sg13g2', (Path(tmp)/'platform-comparison.csv').read_text())

    def power_fixture(self, root):
        run = root/'impl'; directory=run/'power-20260101'; directory.mkdir(parents=True)
        config = dict(name='f3', parameters=dict(ISA_M=1))
        library = root/'nominal.lib'
        library.write_text('nom_voltage : 1.2;\nnom_temperature : 25;\n')
        libraries = {str(library): 'identity'}
        impl = dict(configuration=config, context=dict(platform='ihp-sg13g2',
                    clock_period_ns=60, mapping_libraries=libraries))
        benchmark = dict(workload='elf', context=dict(memory={'latency': 1}, benchmark={'name': 'coremark'}),
            metrics=[dict(name='benchmark_cycles',value=100),dict(name='benchmark_retired',value=50)])
        window = dict(cycles=100, retired=50)
        powers = {'Total': dict(internal=.002, switching=.003, leakage=.001, total=.006)}
        metrics = report.power_measure.energy(powers,100,50,60)
        coverage = report.power_measure.activity_coverage(dict(vcd=100,unannotated=0))
        record = dict(kind='power', status='passed', configuration=config, implementation='impl/report.json',
            workload='elf', benchmark_report='activity/report.json',
            context=dict(platform='ihp-sg13g2', libraries=libraries, clock_period_ns=60,
                memory=benchmark['context']['memory'], benchmark=benchmark['context']['benchmark'],
                stage='placed_pre_cts', timing_qualified=True, clock_model='ideal_pre_cts',
                sta_interconnect='placement_estimated', activity='zero_delay_gate_vcd',
                benchmark_window=window, activity_duration_ps=6000000,
                coverage_minimum=.99, activity_coverage=coverage),
            metrics=[dict(name=k,value=v) for k,v in metrics.items()])
        evidence = dict(status='passed', benchmark_window=window, clock_period_ns=60,
                        coverage=coverage,power=powers,metrics=metrics)
        (directory/'report.json').write_text(json.dumps(record))
        (directory/'power.json').write_text(json.dumps(evidence))
        return impl, benchmark, record, evidence, directory

    def test_power_requires_matching_point_window_and_measured_coverage(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(report,'ROOT',Path(temp)):
            root = Path(temp)
            impl, bench, record, evidence, directory = self.power_fixture(root)
            actual = report.power_results(impl,root/'impl/report.json',bench,root)
            self.assertAlmostEqual(actual['metrics']['dynamic_energy_j'], 30e-9)
            self.assertEqual(actual['libraries'][0]['nom_voltage'], 1.2)
            for field, value in (('workload','other-elf'),('configuration',{'name':'other'})):
                with self.subTest(field=field):
                    (directory/'report.json').write_text(json.dumps(dict(record,**{field:value})))
                    with self.assertRaisesRegex(ValueError,'physical point/workload/window'):
                        report.power_results(impl,root/'impl/report.json',bench,root)
            (directory/'report.json').write_text(json.dumps(record))
            bad = dict(evidence, metrics=dict(evidence['metrics'],dynamic_energy_j=1))
            (directory/'power.json').write_text(json.dumps(bad))
            with self.assertRaisesRegex(ValueError,'power/energy metrics'):
                report.power_results(impl,root/'impl/report.json',bench,root)
            evidence['coverage']['counts'] = dict(input=100,unannotated=0)
            (directory/'power.json').write_text(json.dumps(evidence))
            with self.assertRaisesRegex(ValueError,'insufficient measured'):
                report.power_results(impl,root/'impl/report.json',bench,root)

    def test_energy_export_contains_only_measured_points(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(report,'ROOT',Path(temp)):
            root=Path(temp)
            impl,bench,_,_,_=self.power_fixture(root)
            power=report.power_results(impl,root/'impl/report.json',bench,root)
            data=dict(rows=[dict(platform='ihp-sg13g2',isa='RV32IMC',step=3,power=power),
                            dict(platform='sky130hd',isa='RV32IC',step=0)])
            page=report.power_html(data,root)
            self.assertIn('1.2 V, 25 °C',page)
            self.assertIn('clock-tree implementation',page)
            self.assertNotIn('RV32IC',page)
            text=(root/'energy.csv').read_text()
            self.assertEqual(len(text.splitlines()),2)
            self.assertIn('dynamic_nj_per_instruction',text)

    def test_omit_energy_skips_power_collection_and_removes_navigation(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(report,'ROOT',Path(temp)):
            root=Path(temp); directory=self.fixture(root,'imc',1); output=root/'output'
            path=directory/'summary.json'; summary=json.loads(path.read_text())
            summary['rows'][0]['placement_report']='placement.json'
            path.write_text(json.dumps(summary))
            (root/'placement.json').write_text(json.dumps(dict(status='passed',metrics=[],context={},
                source_sha256={'src/uquintus/uqu_core.v':'same'})))
            with patch.object(report,'implementation_results',return_value={}), \
                    patch.object(report,'power_results',side_effect=AssertionError('energy was read')), \
                    patch('sys.argv',['forwarding_report',str(directory),'--output',str(output),'--omit-energy']), \
                    redirect_stdout(io.StringIO()):
                report.main()
            result=json.loads((output/'summary.json').read_text())
            self.assertEqual(result['power_reporting'],'omitted')
            self.assertIsNone(result['rows'][0]['power'])
            page=(output/'index.html').read_text()
            self.assertNotIn('href="#energy"',page)
            self.assertNotIn('id="energy"',page)


if __name__ == '__main__':
    unittest.main()
