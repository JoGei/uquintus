"""Coverage, trace sharing, source pins and comparison failures for perfsim."""
import io
import json
from pathlib import Path
import sys
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT/'verif/sim/common'))
sys.path.insert(0, str(ROOT/'verif/perfsim'))
import perfsim
from dependencies import digest, extract, fetch, load_lock
from model import describe, render, render_external_bindings
from config_frontend import load_configurations, write_configuration
from hw_config import load_configuration
from compare import compare_streams, cycle_error, iss_records, through_marker, memory_instruction, stream_signature
from calibrate import statistics, write_summary, materialize_matrix


class PerfsimTests(unittest.TestCase):
    def setUp(self):
        self.config = perfsim.configurations(['rv32im_dadda'], 1, 1)[0]['config']

    def test_integer_latency_and_split_translation(self):
        for factor in (1, 2, 4, 8, 16, 32):
            with self.subTest(factor=factor):
                model = describe(dict(self.config, MUA_MUL='iterative', MUA_MULDIV_ITERUNROLL=factor))
                self.assertEqual(model['schedule']['mul_cycles'], 32//factor)
                self.assertEqual(model['schedule']['div_cycles'], (2+factor-1)//factor+32//factor+1)
        split = describe(dict(self.config, MUA_MUL='dadda_mac'))
        self.assertTrue(split['schedule']['split_mul'])
        self.assertEqual(split['status'], 'uncalibrated')

    def test_cycle_neutral_and_inactive_parameters_share_schedule(self):
        original = describe(self.config)
        equivalent = describe(dict(self.config, MUA_REGFILE_IMPL='latch', MUA_DE_OPERAND_RETENTION=1))
        self.assertEqual(original['id'], equivalent['id'])
        no_m = dict(self.config, ISA_M=0)
        self.assertEqual(describe(no_m)['id'], describe(dict(no_m, MUA_MUL='iterative', MUA_MULDIV_ITERUNROLL=1))['id'])
        self.assertEqual(describe(no_m)['coverage']['MUA_MUL'], 'recorded_inactive')
        self.assertNotEqual(original['id'], describe(dict(self.config, MUA_FORWARDING=0))['id'])

    def test_unsupported_active_features_fail_closed(self):
        for name in ('ISA_E', 'ISA_ZFINX', 'ISA_PMP', 'XIF', 'DEBUG', 'ISA_ZIFENCEI'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, name):
                describe(dict(self.config, **{name: 1}))
        for change in (dict(MUA_BTB='direct'), dict(MUA_BRANCH_PREDICTOR='bimodal'),
                       dict(MUA_FORWARD_MEM_TO_DE=0)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                describe(dict(self.config, **change))
        # Disabled paths do not require a model when forwarding is globally off.
        describe(dict(self.config, MUA_FORWARDING=0, MUA_FORWARD_MEM_TO_DE=0))

    def test_memory_latency_and_no_template_placeholders(self):
        for latency in (0, -1, True, 1.5, 10001):
            with self.subTest(latency=latency), self.assertRaises(ValueError):
                describe(self.config, latency)
        for mul in ('iterative', 'dadda', 'dadda_mac'):
            for forwarding in (0, 1):
                d = describe(dict(self.config, MUA_MUL=mul, MUA_FORWARDING=forwarding), 2, 3)
                text = render(d)
                self.assertNotIn('@', text)
                self.assertIn('Fetch(0)', text)
                self.assertIn('Branch(0)', text)
                self.assertIn('uBranch2({Da, Db}', text)
                self.assertIn('uResponse(Response -> {Ld, Committed})', text)
                self.assertIn('Response(3)', text)
                self.assertIn('Architecture(name: "UQU"', text)
                self.assertIn('Delivery -> IfConsumed', text)
                self.assertIn('FrontAdvance -> DeAdvanced', text)

    def test_register_connector_candidate_and_registered_admission_edges(self):
        backend=ROOT/'build/deps/perfsim-upstream/etiss-perf-sim/etiss_plugins/SoftwareEvalLib/libs/backends'
        source=backend/'src/internal/PerformanceModel.cpp'
        compiler=shutil.which('c++')
        if not compiler or not source.is_file():
            self.skipTest('requires provisioned upstream sources and C++ compiler')
        with tempfile.TemporaryDirectory() as tmp:
            exe=Path(tmp)/'register-timing'
            command=[compiler,'-std=c++17','-include','cstdint',
                     '-I'+str(ROOT/'verif/perfsim/models'),'-I'+str(backend/'include/internal'),
                     '-I'+str(backend/'include/api/softwareEval-backends'),
                     str(ROOT/'verif/perfsim/tests/register_timing.cpp'),str(source),'-o',str(exe)]
            built=subprocess.run(command,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            self.assertEqual(built.returncode,0,built.stdout)
            checked=subprocess.run([str(exe)],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            self.assertEqual(checked.returncode,0,checked.stdout)

    def test_compressed_frontend_and_decode_choices(self):
        baseline = describe(dict(self.config, ISA_C=1))
        self.assertTrue(baseline['external_models']['frontendModel']['parameters']['compressed'])
        self.assertNotEqual(baseline['id'], describe(self.config)['id'])
        for impl,stage in (('decompress','if'),('decompress','de'),('decode_compressed','if')):
            config=dict(self.config,ISA_C=1,MUA_C_IMPL=impl,MUA_C_DECOMPRESS_STAGE=stage)
            self.assertEqual(describe(config)['id'],baseline['id'])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'rv32imc.yml'
            path.write_text(yaml.safe_dump(dict(self.config,ISA_C=1)))
            functional=load_configurations([str(path)])[0]['resolved']['functional']
            self.assertEqual(functional['isa'],'rv32imc_zicsr')
            self.assertTrue(functional['etiss']['misa'] & 4)
            trace=Path(tmp)/'trace.csv'
            trace.write_text('1,2147483650,1\n')
            self.assertEqual(list(iss_records(trace)),[(0x80000002,1)])

    def test_frontend_parameters_are_part_of_schedule_identity(self):
        original = describe(self.config)
        for feature in ('none','if_buffer','redirect_request','ifetch_result',
                        'if_buffer+redirect_request+ifetch_result'):
            config=dict(self.config,MUA_REDIRECT_BYPASS=feature,MUA_IF_BUFFER_WORDS=4)
            model=describe(config,3,1)
            self.assertEqual(model['schedule']['redirect_bypass'],feature)
            self.assertEqual(model['schedule']['if_buffer_words'],4)
            self.assertEqual(model['coverage']['MUA_REDIRECT_BYPASS'],'modeled_frontend_queues')
            self.assertNotEqual(model['id'],original['id'])

    def test_config_entry_point_accepts_preset_filename_and_path(self):
        inputs=['rv32im_dadda','rv32im_dadda.yml',str(ROOT/'config/rv32im_dadda.yml')]
        plans=[load_configurations([name])[0]['resolved'] for name in inputs]
        self.assertTrue(all(plan==plans[0] for plan in plans))
        self.assertEqual(plans[0]['configuration']['parameters'],self.config)
        self.assertEqual(plans[0]['functional']['etiss']['misa'],0x40101100)

    def test_config_maps_one_yaml_to_rtl_dsl_and_external_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'experiment.yml'
            config=dict(self.config,HART_ID=5,ISA_UMODE=0,MUA_MUL='iterative',
                        MUA_MULDIV_ITERUNROLL=1,MUA_IF_BUFFER_WORDS=4,
                        MUA_BRANCH_PREDICTOR='static_not_taken',
                        MUA_REDIRECT_BYPASS='if_buffer+redirect_request+ifetch_result')
            path.write_text(yaml.safe_dump(config))
            row=load_configurations([str(path)],3,4)[0]
            plan=row['resolved']
            self.assertEqual(plan['rtl_parameters']['MUA_REDIRECT_BYPASS'],7)
            self.assertEqual(plan['rtl_parameters']['MUA_BRANCH_PREDICTOR'],1)
            self.assertEqual(plan['functional']['etiss']['misa'],0x40001100)
            self.assertEqual(plan['functional']['etiss']['hart_id'],5)
            self.assertEqual(plan['functional']['execution_mode'],'M')
            self.assertEqual(plan['external_models']['frontendModel']['parameters'],dict(
                bypass=7,buffer_words=4,imem_latency=3,static_not_taken=True,compressed=False))
            self.assertEqual(plan['coreperfdsl']['schedule']['mul_cycles'],32)
            self.assertEqual(plan['coreperfdsl']['schedule']['div_cycles'],35)
            output=write_configuration(row,Path(tmp)/'out')
            self.assertIn('Mul(32)',(output/'uqu.corePerfDsl').read_text())
            self.assertIn('Response(4)',(output/'uqu.corePerfDsl').read_text())
            bindings=(output/'external_models.inc').read_text()
            self.assertIn('m->frontendModel.bypass=7;',bindings)
            self.assertIn('m->frontendModel.static_not_taken=true;',bindings)
            self.assertEqual(bindings,render_external_bindings(row['model']))
            self.assertEqual(json.loads((output/'resolved.json').read_text()),plan)
            self.assertEqual(yaml.safe_load((output/'config.yml').read_text()),config)

    def test_config_uses_the_same_complete_schema_as_rtl(self):
        catalog=json.loads((ROOT/'config/selectors.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'invalid.yml'
            for invalid in (dict(self.config,UNRECOGNIZED=0),
                            {k:v for k,v in self.config.items() if k!='ISA_M'}):
                path.write_text(yaml.safe_dump(invalid))
                with self.assertRaises(ValueError) as rtl:
                    load_configuration(path,catalog)
                with self.assertRaises(ValueError) as iss:
                    load_configurations([str(path)])
                self.assertEqual(str(rtl.exception),str(iss.exception))

    def test_config_preserves_hardware_identity_for_cycle_neutral_choices(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths=[]
            for name,backend in (('ff','ff'),('latch','latch')):
                path=Path(tmp)/(name+'.yml')
                path.write_text(yaml.safe_dump(dict(self.config,MUA_REGFILE_IMPL=backend)))
                paths.append(str(path))
            a,b=load_configurations(paths)
            self.assertNotEqual(a['resolved']['configuration']['parameter_sha256'],
                                b['resolved']['configuration']['parameter_sha256'])
            self.assertEqual(a['model']['id'],b['model']['id'])
            self.assertEqual(a['resolved']['functional_id'],b['resolved']['functional_id'])

    def test_config_inspection_does_not_invoke_generators(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(perfsim,'ROOT',Path(tmp)), \
                patch.object(perfsim,'generate') as generate, \
                patch.object(sys,'argv',['perfsim.py','config','--config','rv32im_dadda',
                                        '--etiss-root','/missing-etiss',
                                        '--isa-python','/missing-python']), \
                patch('sys.stdout',new_callable=io.StringIO):
            perfsim.main()
            generate.assert_not_called()
            self.assertTrue((Path(tmp)/'build/uquintus-rv32im_dadda/perfsim/config/resolved.json').is_file())

    def test_external_bindings_reject_non_numeric_runtime_values(self):
        model=describe(self.config)
        model['external_models']['frontendModel']['parameters']['bypass']='7'
        with self.assertRaisesRegex(ValueError,'unsupported external-model value'):
            render_external_bindings(model)

    def test_single_execution_requires_identical_functional_configuration(self):
        perfsim.configurations(['rv32im_dadda', 'rv32im_iterative', 'rv32im_dadda_mac'], 1, 1)
        with self.assertRaisesRegex(ValueError, 'identical ISA'):
            perfsim.configurations(['rv32i', 'rv32im_dadda'], 1, 1)
        with self.assertRaisesRegex(ValueError, 'distinct'):
            perfsim.configurations(['rv32i', 'rv32i'], 1, 1)
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp)/'hart.yml'
            file.write_text(yaml.safe_dump(dict(self.config, HART_ID=5)))
            with self.assertRaisesRegex(ValueError, 'identical ISA'):
                perfsim.configurations(['rv32im_dadda', str(file)], 1, 1)

    def test_lock_is_complete_pinned_and_paths_are_local(self):
        source = ROOT/'config/perfsim/upstream.lock.json'
        data = load_lock(source)
        self.assertGreater(len(data['sources']), 10)
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp)/'lock.json'
            for key, value in (('revision', 'main'), ('archive_sha256', 'bad'), ('path', '../escape')):
                changed = json.loads(source.read_text())
                changed['sources'][1][key] = value
                file.write_text(json.dumps(changed))
                with self.subTest(key=key), self.assertRaises(ValueError):
                    load_lock(file)

    def test_archives_reject_escape_and_checksum_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root/'source.tar.gz'
            with tarfile.open(archive, 'w:gz') as output:
                for name in ('prefix/good', 'prefix/../../escape'):
                    item = tarfile.TarInfo(name)
                    item.size = 1
                    output.addfile(item, io.BytesIO(b'x'))
            with self.assertRaisesRegex(ValueError, 'unsafe'):
                extract(archive, root/'unpacked')
            row = dict(path='', repository='example/repo', revision='a'*40, archive_sha256=digest(archive))
            cache = root/'cache'; cache.mkdir()
            cached = cache/('example-repo-'+'a'*40+'.tar.gz')
            cached.write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                fetch(dict(sources=[row]), root/'destination', cache, offline=True)
            cached.unlink()
            with self.assertRaisesRegex(ValueError, 'missing offline'):
                fetch(dict(sources=[row]), root/'destination', cache, offline=True)

    def test_trace_comparison_rejects_missing_changed_and_extra_instructions(self):
        good = [(0x80000000, 0x93), (0x80000004, 0x193)]
        self.assertEqual(compare_streams(iter(good), iter(good)), 2)
        for bad in (good[:-1], good+[(8, 0x13)], [(0x80000000, 0x13)], []):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                compare_streams(iter(good), iter(bad))
        with self.assertRaisesRegex(ValueError, 'empty'):
            compare_streams(iter([]), iter([]))

    def test_trace_reader_checks_index_and_alignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp)/'trace.csv'
            file.write_text('1,2147483648,147\n')
            self.assertEqual(list(iss_records(file)), [(0x80000000, 147)])
            for text in ('2,0,147\n', '1,1,147\n', '1,0\n'):
                file.write_text(text)
                with self.assertRaises(ValueError):
                    list(iss_records(file))

    def test_matrix_expands_to_complete_validated_core_yamls(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths=materialize_matrix(ROOT/'config/perfsim/rv32imc-accuracy.yml',Path(tmp)/'configs')
            self.assertEqual(len(paths),13)
            rows=load_configurations(paths)
            self.assertTrue(all(r['config']['ISA_C']==1 for r in rows))
            self.assertTrue(all(set(r['config'])==set(self.config) for r in rows))
            self.assertEqual(len({r['resolved']['functional_id'] for r in rows}),1)
            self.assertEqual(len({r['model']['id'] for r in rows}),10)
            invalid=Path(tmp)/'matrix.yml'
            invalid.write_text(yaml.safe_dump(dict(base='rv32im_dadda',prefix='test',common={},
                                                   cases=dict(bad=dict(UNKNOWN_PARAMETER=1)))))
            with self.assertRaisesRegex(ValueError,'unknown'):
                materialize_matrix(invalid,Path(tmp)/'invalid')

    def test_stream_signatures_preserve_pc_code_order_and_count(self):
        rows=[(0x80000000,1),(0x80000002,0x13)]
        expected=stream_signature(iter(rows))
        self.assertEqual(expected[0],2)
        self.assertEqual(expected,stream_signature(iter(rows)))
        self.assertNotEqual(expected,stream_signature(iter(rows[::-1])))
        self.assertNotEqual(expected,stream_signature(iter(rows[:-1])))
        with self.assertRaisesRegex(ValueError,'empty'):
            stream_signature(iter([]))

    def test_fast_trace_only_removes_successor_bytes_for_compressed_ops(self):
        self.assertEqual(memory_instruction(0x41814081),0x4081)
        self.assertEqual(memory_instruction(0x12340013),0x12340013)
        self.assertEqual(memory_instruction(0x00000001),1)

    def test_accuracy_summary_retains_sign_worst_case_and_failures(self):
        results=[dict(status='passed',configuration='a',workload='one',window_instructions=50,
                      comparison=dict(timing_error=cycle_error(90,100))),
                 dict(status='passed',configuration='a',workload='two',window_instructions=50,
                      comparison=dict(timing_error=cycle_error(120,100))),
                 dict(status='failed',configuration='a',workload='three')]
        summary=statistics(results)
        self.assertEqual(summary['pairs'],2)
        self.assertAlmostEqual(summary['mean_signed_relative_error'],0.05)
        self.assertAlmostEqual(summary['mean_absolute_relative_error'],0.15)
        self.assertAlmostEqual(summary['max_absolute_relative_error'],0.2)
        with tempfile.TemporaryDirectory() as tmp:
            record=dict(results=results,status='failed')
            write_summary(Path(tmp),record)
            table=(Path(tmp)/'accuracy.md').read_text()
            self.assertIn('RTL CPI',table)
            self.assertIn('-10.00%',table)
            self.assertIn('FAILED',table)
            self.assertEqual(json.loads((Path(tmp)/'accuracy.json').read_text())['status'],'failed')

    def test_stop_marker_excludes_timing_dependent_output(self):
        rows = [(0, 0x13), (4, 0xb0002573), (8, 0x13)]
        self.assertEqual(list(through_marker(iter(rows), 4)), rows[:2])
        with self.assertRaisesRegex(ValueError, 'stop marker'):
            list(through_marker(iter(rows), 12))

    def test_cycle_error_keeps_sign_and_absolute_error(self):
        result = cycle_error(90, 100)
        self.assertEqual(result['signed_cycles'], -10)
        self.assertEqual(result['absolute_cycles'], 10)
        self.assertAlmostEqual(result['relative_error'], -0.1)
        self.assertAlmostEqual(result['absolute_relative_error'], 0.1)
        with self.assertRaises(ValueError):
            cycle_error(True, 100)


if __name__ == '__main__':
    unittest.main()
