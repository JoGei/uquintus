"""Check the experiment's evidence joins and qualified candidate selection."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
SPEC=importlib.util.spec_from_file_location('bpu_sweep',ROOT/'impl/asic/orfs/investigations/bpu_replay_sweep.py')
sweep=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sweep)


class BpuSweepTests(unittest.TestCase):
    def test_frontier_excludes_failed_points_and_retains_equal_points(self):
        rows=[dict(name=name,qualified=valid,area_um2=area,execution_time_ms=time)
              for name,valid,area,time in [('small',True,10,30),('fast',True,30,10),
                  ('dominated',True,35,35),('tie',True,10,30),('failed',False,1,1)]]
        self.assertEqual({r['name'] for r in sweep.frontier(rows)}, {'small','fast','tie'})

    def test_cycles_and_timing_use_distinct_artifacts_and_correct_units(self):
        case=dict(name='point',bp=2,btb=4,hwords=1)
        benchmark=dict(status='passed',metrics=[dict(name='benchmark_cycles',value=1500000),
                                               dict(name='benchmark_retired',value=750000)])
        placement=dict(status='passed',metrics=[dict(name='minimum_clock_period',value=25),
                                               dict(name='cell_area',value=200000)])
        result=sweep.collect(case,benchmark,placement,'sky130hd')
        self.assertTrue(result['qualified'])
        self.assertEqual(result['execution_time_ms'],37.5)
        self.assertEqual(result['cycles'],1500000)
        placement['status']='failed'
        self.assertFalse(sweep.collect(case,benchmark,placement,'sky130hd')['qualified'])

    def test_recorded_input_mutation_prevents_reuse(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(sweep,'ROOT',Path(tmp)):
            source=Path(tmp)/'rtl.v';source.write_text('original')
            record=dict(input_sha256={'rtl.v':sweep.sha(source)})
            self.assertTrue(sweep.fresh(record))
            source.write_text('changed')
            self.assertFalse(sweep.fresh(record))
            source.unlink()
            self.assertFalse(sweep.fresh(record))
            self.assertFalse(sweep.fresh({}))

    def test_html_and_json_cover_pending_and_qualified_points(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(sweep,'ROOT',Path(tmp)):
            root=Path(tmp);directory=root/'comparison';directory.mkdir()
            (root/'bench.json').write_text(json.dumps(dict(status='passed',metrics=[
                dict(name='benchmark_cycles',value=1000)])))
            (root/'place.json').write_text(json.dumps(dict(status='passed',metrics=[
                dict(name='cell_area',value=100),dict(name='minimum_clock_period',value=25)])))
            manifest=dict(context=dict(clock_period_ns=40),platforms=['sky130hd','ihp-sg13g2'],cases=[
                dict(name='bpu-b16-t16-h16',bp=16,btb=16,hwords=16,benchmark='bench.json',sky130hd='place.json'),
                dict(name='pending',bp=8,btb=8,hwords=8),
                dict(name='packed',bp=8,btb=8,hwords=6,benchmark='bench.json',sky130hd='place.json')])
            rows=sweep.render(directory,manifest)
            self.assertEqual(len(rows),3)
            self.assertTrue(rows[0]['local_frontier'])
            self.assertFalse(rows[1]['qualified'])
            self.assertIn('40 ns target',(directory/'index.html').read_text())
            self.assertIn('../place.json',(directory/'index.html').read_text())
            self.assertIn('3 fixed configurations',(directory/'index.html').read_text())
            self.assertIn('payload halfwords 6/8/16',(directory/'index.html').read_text())
            self.assertIn('stroke="#db6279"',(directory/'index.html').read_text())
            self.assertIn('stroke="#5d9c42"',(directory/'index.html').read_text())
            self.assertNotIn('style="color:#a563bd">2<',(directory/'index.html').read_text())
            self.assertEqual(json.loads((directory/'summary.json').read_text())['rows'],rows)

    def test_expanded_matrix_covers_all_independent_capacities_and_halfwords(self):
        points=set(sweep.itertools.product(sweep.CAPACITIES,sweep.CAPACITIES,sweep.HWORDS))
        self.assertEqual(len(points),80)
        self.assertIn((16,16,16),points)
        self.assertIn((2,16,16),points)
        self.assertIn((16,2,8),points)

    def test_selected_rv32ic_points_include_packed_budget_and_matching_references(self):
        points=sweep.candidate_points(ROOT/'impl/asic/orfs/investigations/bpu_rv32ic_candidates.yml')
        self.assertEqual(len(points),13)
        self.assertIn((8,8,6),points)
        self.assertIn((16,8,6),points)
        self.assertIn((16,16,8),points)
        for bp,btb,hwords in points:
            self.assertIn((bp,btb,0),points)
        self.assertEqual(len(sweep.candidate_points()),80)

    def test_candidate_validation_rejects_invalid_and_duplicate_points(self):
        import yaml
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'candidates.yml'
            for points in ([],{},[[8,8]],[[8,8,True]],[[3,8,6]],[[8,8,-1]],
                           [[8,8,2049]],[[8,8,6],[8,8,6]]):
                path.write_text(yaml.safe_dump(points))
                with self.subTest(points=points),self.assertRaises(ValueError):
                    sweep.candidate_points(path)

    def test_c_variants_change_only_compressed_implementation_and_keep_if_names(self):
        import yaml
        base=yaml.safe_load((ROOT/'config/rv32ic_bimodal_idata.yml').read_text())
        points=sweep.candidate_points(ROOT/'impl/asic/orfs/investigations/bpu_rv32ic_candidates.yml')
        old,original=sweep.make_cases(base,points,'bpu-c')
        cases,configs=sweep.make_cases(base,points,'bpu-c',list(sweep.C_VARIANTS))
        self.assertEqual(len(cases),39)
        self.assertEqual(len({c['name'] for c in cases}),39)
        for case in cases:
            plain=f"bpu-c-b{case['bp']}-t{case['btb']}-h{case['hwords']}"
            expected=dict(original[plain],**sweep.C_VARIANTS[case['c_variant']])
            self.assertEqual(configs[case['name']],expected)
            self.assertEqual(sweep.compressed_variant(expected),case['c_variant'])
            if case['c_variant']=='decompr-if':
                self.assertEqual(case['name'],plain)
                self.assertEqual(configs[plain],original[plain])
        for variants in ([],['decompr-if','decompr-if'],['unsupported']):
            with self.subTest(variants=variants),self.assertRaises(ValueError):
                sweep.make_cases(base,points,'bpu-c',variants)
        with self.assertRaisesRegex(ValueError,'ISA_C=1'):
            sweep.make_cases(dict(base,ISA_C=0),points,'bpu-c',['cdecode'])

    def test_ihp_selection_uses_each_c_variant_and_matching_h0_reference(self):
        rows=[]
        for variant in sweep.C_VARIANTS:
            for suffix,bp,h,area,time in [('small',2,0,10,30),('anchor',8,0,20,25),
                                         ('fast',8,6,30,10),('other',4,4,25,26)]:
                rows.append(dict(name=variant+suffix,c_variant=variant,bp=bp,btb=bp,hwords=h,
                                 area_um2=area,execution_time_ms=time))
        selected=sweep.ihp_candidates(rows,rows,['nonexistent'])
        self.assertEqual(len(selected),9)
        for variant in sweep.C_VARIANTS:
            self.assertEqual({r['name'] for r in selected if r['c_variant']==variant},
                             {variant+s for s in ('small','anchor','fast')})

    def test_c_variant_markers_are_distinct_without_fills(self):
        for variant,tag in [('decompr-if','circle'),('decompr-de','rect'),('cdecode','polygon')]:
            row=dict(name='point',c_variant=variant,area_um2=100,t_min_ns=25,
                     execution_time_ms=1,placement_status='passed',local_frontier=True,qualified=True)
            mark=sweep.marker(row,10,20,'#123456')
            self.assertIn('<'+tag,mark)
            self.assertIn('fill="none"',mark)
            self.assertIn(variant,mark)

    def test_frequency_render_matches_if_reference_at_identical_bpu_point(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(sweep,'ROOT',Path(tmp)):
            root=Path(tmp);directory=root/'comparison';directory.mkdir()
            (root/'bench.json').write_text(json.dumps(dict(status='passed',metrics=[
                dict(name='benchmark_cycles',value=1000),dict(name='benchmark_cpi',value=2)])))
            cases=[]
            for variant,period in [('decompr-if',30),('decompr-de',25),('cdecode',20)]:
                report=variant+'.json'
                (root/report).write_text(json.dumps(dict(status='passed',metrics=[
                    dict(name='minimum_clock_period',value=period),dict(name='cell_area',value=100),
                    dict(name='estimated_fmax',value=1000/period)])))
                cases.append(dict(name=variant,bp=8,btb=8,hwords=6,c_variant=variant,
                                  benchmark='bench.json',sky130hd=report))
            # A different table capacity must not silently use the 8/8 IF reference.
            cases.append(dict(name='unmatched',bp=16,btb=8,hwords=6,c_variant='cdecode',
                              benchmark='bench.json',sky130hd='cdecode.json'))
            sweep.render(directory,dict(context=dict(clock_period_ns=40),platforms=['sky130hd'],cases=cases))
            page=(directory/'index.html').read_text()
            self.assertIn('Area versus estimated frequency',page)
            self.assertIn('>-16.67%</td>',page)
            self.assertEqual(page.count('>-33.33%</td>'),1)
            for tag in ('circle','rect','polygon'):
                self.assertIn('<'+tag,page)

    def test_flow_invocations_keep_distinct_logs_and_reject_incomplete_reports(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(sweep,'ROOT',Path(tmp)):
            root=Path(tmp);(root/'logs').mkdir();artifact=root/'artifact';artifact.mkdir()
            report=artifact/'report.json';report.write_text(json.dumps(dict(status='passed')))
            def run(command, cwd, stdout, stderr):
                stdout.write(f'Artifacts: {artifact}\n')
                return SimpleNamespace(returncode=0)
            args=SimpleNamespace(jobs=2,bender='bender',elf=root/'program.elf')
            case=dict(name='point')
            with patch.object(sweep.subprocess,'run',side_effect=run):
                for _ in range(2):
                    self.assertEqual(sweep.execute(case,'benchmark',args,root,{},'elf'),
                                     ('artifact/report.json',False))
                self.assertEqual(len(list((root/'logs').glob('point-benchmark-*.log'))),2)
                report.write_text(json.dumps(dict(status='running')))
                with self.assertRaisesRegex(RuntimeError,'incomplete report'):
                    sweep.execute(case,'benchmark',args,root,{},'elf')

    def test_audit_rejects_mixed_workloads_and_rtl(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(sweep,'ROOT',Path(tmp)):
            root=Path(tmp);(root/'config').mkdir()
            cases=[]
            for name in ('a','b'):
                parameters={'MUA_BP_ENTRIES':2}
                (root/'config'/f'{name}.yml').write_text('MUA_BP_ENTRIES: 2\n')
                record=dict(status='passed',configuration=dict(parameters=parameters),
                    source_sha256={'src/uquintus/uqu_core.v':'same-rtl'},workload='same-elf',
                    context=dict(memory=dict(imem_latency=1,dmem_latency=1)),
                    metrics=[dict(name='benchmark_retired',value=100)])
                (root/f'{name}.json').write_text(json.dumps(record))
                cases.append(dict(name=name,benchmark=f'{name}.json'))
            manifest=dict(cases=cases,platforms=['sky130hd'],context=dict(elf_sha256='same-elf'))
            self.assertEqual(sweep.audit(root,manifest)['checked_records'],2)
            record['workload']='different-elf'
            (root/'b.json').write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError,'ELF mismatch'):
                sweep.audit(root,manifest)
            record['workload']='same-elf'
            record['source_sha256']['src/uquintus/uqu_core.v']='different-rtl'
            (root/'b.json').write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError,'RTL inputs differ'):
                sweep.audit(root,manifest)
