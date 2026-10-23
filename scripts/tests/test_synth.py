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
    def test_wire_load_policy_rejects_disabled_missing_or_duplicate_commands(self):
        commands=['buffer -c','topo','stime -c','upsize -c','dnsize -c']
        with tempfile.TemporaryDirectory() as tmp:
            script=Path(tmp)/'abc_speed.script'
            script.write_text('# Upstream script\n'+'\n'.join(commands)+'\n')
            policy=synth.abc_wire_load_policy(script)
            self.assertTrue(policy['abc_wire_loads'])
            self.assertEqual(policy['abc_script_sha256'],synth.digest(script))
            for command in ('buffer -c','stime -c','upsize -c','dnsize -c'):
                for changed in (command.removesuffix(' -c'),'# '+command,command+'\n'+command):
                    script.write_text('\n'.join(changed if line==command else line for line in commands))
                    with self.subTest(command=command,changed=changed),self.assertRaises(ValueError):
                        synth.abc_wire_load_policy(script)

    def test_orfs_overrides_cannot_silently_change_buffering_policy(self):
        good='LIB_FILES: /pdk/cells.lib\nABC_AREA: 0\nREMOVE_ABC_BUFFERS: 1\nGPL_TIMING_DRIVEN: 1\n'
        self.assertEqual(synth.resolved_buffering_settings(good),synth.BUFFERING_SETTINGS)
        for changed in (good.replace('ABC_AREA: 0','ABC_AREA: 1'),
                        good.replace('REMOVE_ABC_BUFFERS: 1','REMOVE_ABC_BUFFERS: 0'),
                        good.replace('GPL_TIMING_DRIVEN: 1','GPL_TIMING_DRIVEN: 0'),
                        good.replace('REMOVE_ABC_BUFFERS: 1\n',''),
                        good+'ABC_AREA: 0\n'):
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                synth.resolved_buffering_settings(changed)

    def test_executed_abc_script_and_retained_hash_must_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            script=Path(tmp)/'abc_speed.script';script.write_text('buffer -c\n')
            log=Path(tmp)/'yosys.log'
            expected=synth.digest(script)
            log.write_text(f'abc -script {script} -liberty cells.lib\nTook 1 second: abc -script {script}\n')
            synth.check_abc_execution(log,script,expected)
            for command in ('no mapping evidence',f'abc -script {script}.other',
                            'abc_new -liberty cells.lib'):
                log.write_text(command+'\n')
                with self.subTest(command=command),self.assertRaises(ValueError):
                    synth.check_abc_execution(log,script,expected)
            log.write_text(f'abc -script {script}\n')
            script.write_text('buffer\n')
            with self.assertRaisesRegex(ValueError,'changed during synthesis'):
                synth.check_abc_execution(log,script,expected)

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

    def test_ics55_requires_the_exact_qualified_pdk_assets(self):
        with self.assertRaisesRegex(ValueError,'requires ICS55_PDK_ROOT'):
            synth.ics55_pdk('')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for relative in synth.ICS55_ASSETS.values():
                path=root/relative
                path.parent.mkdir(parents=True,exist_ok=True)
                path.touch()
            actual,files=synth.ics55_pdk(root)
            self.assertEqual(actual,root.resolve())
            self.assertEqual(set(files),set(synth.ICS55_ASSETS))
            files['typ_liberty'].unlink()
            with self.assertRaisesRegex(ValueError,'typ_tt_1p2_25'):
                synth.ics55_pdk(root)


if __name__=='__main__':unittest.main()
