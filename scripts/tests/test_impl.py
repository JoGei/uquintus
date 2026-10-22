"""Physical runs must retain real constraints, path scope and legal cell evidence."""
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest

SOURCE=Path(__file__).resolve().parents[2]/'impl/asic/orfs/common/synth.py'
SPEC=importlib.util.spec_from_file_location('uqu_implementation',SOURCE)
flow=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(flow)


class ImplementationTests(unittest.TestCase):
    def test_supplied_sdc_replaces_generic_assumptions_and_cannot_mix_reset_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'system.sdc'
            text='create_clock -name system -period 12 [get_ports clk_i]\n'
            source.write_text(text)
            actual,path,context=flow.constraint_profile(12,None,str(source))
            self.assertEqual(actual,text)
            self.assertEqual(path,source)
            self.assertEqual(context['constraint_profile'],'integration')
            self.assertEqual(context['sdc_sha256'],flow.digest(source))
            self.assertNotIn('io_delay_fraction',context)
            self.assertNotIn('reset_input_max_delay_ns',context)
            with self.assertRaises(ValueError): flow.constraint_profile(12,1,str(source))
            source.write_text('')
            with self.assertRaises(ValueError): flow.constraint_profile(12,None,str(source))
            _,path,context=flow.constraint_profile(20,1,'')
            self.assertIsNone(path)
            self.assertEqual(context['reset_input_max_delay_ns'],1)

    def test_invalid_geometry_and_density_fail_before_launching_tools(self):
        settings,context=flow.implementation_settings('0 0 1240 1240','20 20 1220 1220',0.65)
        self.assertEqual(settings['CORE_AREA'],'20 20 1220 1220')
        self.assertEqual(context['die_area_um'],[0,0,1240,1240])
        for die,core,density in [('0 0 0 10','1 1 2 2',0.5),('0 0 10 10','1 1 11 9',0.5),
                                 ('0 0 10 nan','1 1 9 9',0.5),('0 0 10 10','1 1 9',0.5),
                                 ('0 0 10 10','1 1 9 9',math.nan),('0 0 10 10','1 1 9 9',1)]:
            with self.subTest(die=die,core=core,density=density),self.assertRaises(ValueError):
                flow.implementation_settings(die,core,density)

    def test_timing_scope_never_converts_missing_paths_into_an_internal_frequency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'timing/placed_pre_cts';folder.mkdir(parents=True)
            values=dict(clock_period_ns=20,minimum_clock_period=16,estimated_fmax=62.5,
                        setup_worst_slack=4,hold_worst_slack=-0.1,setup_total_negative_slack=0,
                        slew_violations=2,capacitance_violations=0,fanout_violations=0)
            metrics=folder/'metrics.tsv'
            metrics.write_text(''.join(f'{k}\t{v}\n' for k,v in values.items()))
            (folder/'clock.txt').write_text('core_clk\n')
            lines=['full\tmax\t4\tboot_addr_i[0]\tu_pc/D','full\tmin\t-0.1\tu_a/Q\tu_b/D']
            for scope in ('reg_to_reg','input_to_reg','reg_to_output','input_to_output'):
                lines.extend([scope+'\tmax\tno_paths',scope+'\tmin\tno_paths'])
            paths=folder/'paths.tsv';paths.write_text('\n'.join(lines)+'\n')
            summary=flow.timing_summary(root,'placed_pre_cts',20)
            self.assertEqual(summary['paths']['reg_to_reg_max'],dict(status='no_paths'))
            self.assertEqual(summary['metrics']['hold_worst_slack'],-0.1)
            self.assertEqual(summary['metrics']['slew_violations'],2)
            self.assertEqual(summary['paths']['full_max']['startpoint'],'boot_addr_i[0]')
            with self.assertRaisesRegex(ValueError,'clock period'):
                flow.timing_summary(root,'placed_pre_cts',10)
            for changed in [lines[:-1],[line.replace('full\tmax\t4','full\tmax\t3') for line in lines],
                            [line.replace('full\tmax\t4','full\tmax\tnan') for line in lines]]:
                paths.write_text('\n'.join(changed)+'\n')
                with self.assertRaises(ValueError): flow.timing_summary(root,'placed_pre_cts',20)
            self.assertTrue((folder/'summary.json').is_file())

    def test_physical_area_and_legality_are_distinct_from_liberty_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'physical';folder.mkdir()
            (folder/'placement_violations.txt').write_text('0\n')
            (folder/'cells.tsv').write_text('gate\t3\t4.1\nbuf\t2\t2.2\ntap\t1\t1.5\n')
            modules={'gate':dict(attributes=dict(area='4')),
                     'buf':dict(attributes=dict(area='2'),ports={
                         'A':dict(direction='input',bits=[1]),'Y':dict(direction='output',bits=[1])})}
            metrics={m['name']:m['value'] for m in flow.placed_metrics(root,modules)}
            self.assertEqual(metrics['cell_count'],6)
            self.assertEqual(metrics['cell_area'],16)
            self.assertAlmostEqual(metrics['lef_cell_area'],18.2)
            self.assertEqual(metrics['physical_only_count'],1)
            self.assertEqual(metrics['buffer_count'],2)
            self.assertEqual(json.loads((folder/'cells.json').read_text())['gate'],3)
            (folder/'placement_violations.txt').write_text('1\n')
            with self.assertRaises(ValueError): flow.placed_metrics(root,modules)


if __name__=='__main__': unittest.main()
