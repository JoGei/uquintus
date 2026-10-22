"""Synthesis evidence must reject missing timing, blackboxes and corrupt counts."""
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[2]/'impl/asic/orfs/common/synth.py'
SPEC=importlib.util.spec_from_file_location('uqu_synthesis',SOURCE)
synth=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(synth)


class SynthesisTests(unittest.TestCase):
    def test_buffer_metrics_use_library_function_instead_of_cell_names(self):
        def module(input_bits,output_bits,area):
            return dict(attributes=dict(area=area),ports={
                'A':dict(direction='input',bits=input_bits),
                'Y':dict(direction='output',bits=output_bits)})
        modules={'arbitrary_name':module([2],[2],'3.75'),
                 'clock_driver':module([9],[9],'5.5'),
                 'misleading_buf_name':module([2],[3],'4'),
                 'tie':module(['0'],['0'],'2'),
                 'unrelated':dict(attributes={})}
        metrics=synth.buffer_metrics(modules,dict(arbitrary_name=4,clock_driver=2,
            misleading_buf_name=10,tie=1,unrelated=3))
        self.assertEqual(metrics,[dict(name='buffer_count',value=6,unit='cells'),
                                  dict(name='buffer_area',value=26.0,unit='um2')])
        modules['arbitrary_name']['attributes']['area']='nan'
        with self.assertRaises(ValueError):
            synth.buffer_metrics(modules,{'arbitrary_name':1})

    def test_tool_failure_retains_actionable_diagnostic(self):
        failure=subprocess.CalledProcessError(1,['yosys'],output="Can't load Slang plugin")
        with patch.object(synth.subprocess,'check_output',side_effect=failure):
            with self.assertRaisesRegex(RuntimeError,"Can't load Slang plugin"):
                synth.output(['yosys'])

    def test_orfs_archive_and_unrelated_ancestor_have_no_invented_revision(self):
        with patch.object(synth,'output',side_effect=RuntimeError('not a repository')):
            self.assertIsNone(synth.orfs_revision(Path('/opt/orfs/flow')))
        with patch.object(synth,'output',return_value='/unrelated'):
            self.assertIsNone(synth.orfs_revision(Path('/opt/orfs/flow')))
        with patch.object(synth,'output',side_effect=['/opt/orfs','revision']):
            self.assertEqual(synth.orfs_revision(Path('/opt/orfs/flow')),'revision')

    def test_mapping_evidence_rejects_unmapped_blackbox_empty_or_wrong_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            stat=Path(tmp)/'stat.json';netlist=Path(tmp)/'mapped.json'
            def write(cell='gate',count=1,area=2.5,library=True):
                stat.write_text(json.dumps(dict(design=dict(num_cells=count,area=area))))
                modules={'top':dict(cells={'u':dict(type=cell)}),
                         cell:dict(attributes={'liberty_cell':'1'} if library else {})}
                netlist.write_text(json.dumps(dict(modules=modules)))
            write()
            metrics,counts=synth.mapped_metrics(stat,netlist,'top')
            self.assertEqual(counts,{'gate':1})
            self.assertEqual(metrics[1],dict(name='cell_area',value=2.5,unit='um2'))
            for changes in (dict(cell='$add'),dict(library=False),dict(count=0),dict(count=2),
                            dict(area=0),dict(area=math.nan)):
                write(**changes)
                with self.subTest(changes=changes),self.assertRaises(ValueError):
                    synth.mapped_metrics(stat,netlist,'top')

    def test_timing_units_and_missing_or_nonfinite_measurements(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'timing.json'
            good={'synth__timing__setup__ws':-3.25,'synth__timing__setup__tns':-100,
                  'synth__timing__fmax':40e6}
            path.write_text(json.dumps(good))
            result=synth.timing_metrics(path)
            self.assertEqual(result[0],dict(name='setup_worst_slack',value=-3.25,unit='ns'))
            self.assertEqual(result[-1],dict(name='estimated_fmax',value=40,unit='MHz'))
            for key in good:
                for value in (None,math.nan,math.inf,'40'):
                    path.write_text(json.dumps(dict(good,**{key:value})))
                    with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                        synth.timing_metrics(path)
            path.write_text(json.dumps(dict(good,synth__timing__fmax=0)))
            with self.assertRaises(ValueError):synth.timing_metrics(path)

    def test_invalid_constraint_and_make_paths_fail_early(self):
        for period in (0,-1,math.nan,math.inf):
            with self.subTest(period=period),self.assertRaises(ValueError):synth.sdc(period)
        self.assertIn('-period 20',synth.sdc(20))
        self.assertIn('[all_inputs -no_clocks]',synth.sdc(20))
        for path in ('a b','a\nb','a$b','a#b','a\\b'):
            with self.subTest(path=path),self.assertRaises(ValueError):synth.make_path(path)

    def test_reset_arrival_override_preserves_data_budget_and_checks_hold(self):
        legacy=synth.sdc(20)
        self.assertNotIn('get_ports rst_ni',legacy)
        trial=synth.sdc(20,1)
        self.assertIn('set_input_delay 4 -clock core_clk $data_inputs',trial)
        self.assertIn('set_output_delay 4 -clock core_clk [all_outputs]',trial)
        self.assertIn('set_input_delay -min 0 -clock core_clk [get_ports rst_ni]',trial)
        self.assertIn('set_input_delay -max 1 -clock core_clk [get_ports rst_ni]',trial)
        self.assertIn('set_clock_uncertainty 0.1',trial)
        self.assertNotIn('set_false_path',trial)
        self.assertNotIn('set_multicycle_path',trial)
        self.assertIn('set_input_delay -max 0 ',synth.sdc(20,0))
        for delay in (-1,math.nan,math.inf):
            with self.subTest(delay=delay),self.assertRaises(ValueError):synth.sdc(20,delay)

    def test_external_orfs_root_takes_precedence_over_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow=Path(tmp)/'flow';flow.mkdir();(flow/'Makefile').touch()
            with patch.object(synth,'output',side_effect=AssertionError('must not call launcher')):
                self.assertEqual(synth.flow_directory(tmp),flow)
                with self.assertRaises(ValueError):synth.flow_directory(str(flow))
            with patch.object(synth.shutil,'which',return_value='/env/orfs'), \
                 patch.object(synth,'output',return_value=str(flow)) as command:
                self.assertEqual(synth.flow_directory(''),flow)
                command.assert_called_once_with(['/env/orfs','--flow-dir'])


if __name__=='__main__':unittest.main()
