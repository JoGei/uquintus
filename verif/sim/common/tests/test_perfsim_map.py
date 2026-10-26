"""Pinned MAPExplorer integration contracts and native runtime hooks."""
from pathlib import Path
from types import SimpleNamespace
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT/'verif/perfsim'))
from map_explorer import STAGES, UquMapping, load_profile


class Graph:
    def __init__(self): self.edges = {}
    def add_edge(self, source, target, **data): self.edges[source, target] = data
    def __contains__(self, node): return any(node in edge for edge in self.edges)
    def in_edges(self, target, data=False):
        return [(a, b, d) for (a, b), d in self.edges.items() if b == target]


class MappingTests(unittest.TestCase):
    def test_environment_derivation_and_checked_rtl_reuse(self):
        import calibrate
        from dependencies import digest
        import yaml
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);sw=root/'sw';sw.mkdir();elf=sw/'program.elf';elf.write_bytes(b'unchanged ELF')
            metadata=dict(benchmark=dict(memory=dict(imem_latency=1,dmem_latency=1),max_cycles=100),
                          elf_sha256=digest(elf),status='passed')
            (sw/'build.json').write_text(json.dumps(metadata))
            with mock.patch.object(calibrate,'ROOT',root):
                derived=calibrate.environment_workload(elf,5,3)
                data=json.loads((derived.parent/'build.json').read_text())
                self.assertEqual(derived.read_bytes(),elf.read_bytes())
                self.assertEqual(data['benchmark']['memory'],dict(imem_latency=5,dmem_latency=3))
                self.assertEqual(data['environment_derivation']['parent_sha256'],digest(sw/'build.json'))
                rtl=root/'rtl';rtl.mkdir();source=root/'rtl.v';source.write_text('module original; endmodule')
                trace=rtl/'retire.bin';trace.write_bytes(b'trace')
                config={'ISA_C':1};(rtl/'config.yml').write_text(yaml.safe_dump(config))
                report=dict(status='passed',source_sha256={'rtl.v':digest(source)},
                    diagnostic_retirement_trace=dict(file='retire.bin',sha256=digest(trace)))
                (rtl/'report.json').write_text(json.dumps(report))
                (rtl/'benchmark.json').write_text(json.dumps(dict(memory=data['benchmark']['memory'])))
                evidence=dict(status='passed',results=[dict(status='passed',elf=str(elf),rtl=str(rtl))])
                self.assertEqual(calibrate.retained_rtl(evidence,config,derived),rtl)
                self.assertIsNone(calibrate.retained_rtl(evidence,{'ISA_C':0},derived))
                source.write_text('changed')
                with self.assertRaisesRegex(ValueError,'input changed'):calibrate.retained_rtl(evidence,config,derived)
                source.write_text('module original; endmodule');trace.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'trace changed'):calibrate.retained_rtl(evidence,config,derived)

    def test_frontend_envelope_configuration_and_sharing_identity(self):
        sys.path.insert(0,str(ROOT/'verif/sim/common'))
        from config_frontend import load_configurations
        from model import describe
        row=load_configurations(['rv32im_dadda'],contract='map_dse')[0]
        config=dict(row['config'],MUA_BRANCH_PREDICTOR='none')
        a=describe(config,contract='map_dse')
        fetch=a['external_models']['fetchModel']['parameters']
        self.assertFalse(fetch['static_not_taken'])
        self.assertEqual(fetch['buffer_words'],config['MUA_IF_BUFFER_WORDS'])
        self.assertEqual(fetch['dmem_latency'],1)
        self.assertEqual(a['coverage']['MUA_IF_BUFFER_WORDS'],'trace_driven_queue_envelope')
        b=describe(dict(config,MUA_MULDIV_ITERUNROLL=1),contract='map_dse')
        self.assertNotEqual(a['external_models']['fetchModel'],b['external_models']['fetchModel'])
        # Backend occupancy belongs to the envelope identity. BPU state uses
        # that clock too, so capacities alone do not permit sharing.
        slow=describe(config,dmem_latency=3,contract='map_dse')
        self.assertEqual(slow['external_models']['fetchModel']['parameters']['dmem_latency'],3)
        self.assertNotEqual(a['external_models']['fetchModel'],slow['external_models']['fetchModel'])
        static=describe(dict(config,MUA_BRANCH_PREDICTOR='static_not_taken'),contract='map_dse')
        self.assertEqual(a['external_models']['frontendModel'],static['external_models']['frontendModel'])

    def test_bpu_parameters_and_retention_coverage(self):
        sys.path.insert(0,str(ROOT/'verif/sim/common'))
        from config_frontend import load_configurations
        from model import describe
        config=load_configurations(['rv32im_dadda'],contract='map_dse')[0]['config']
        b=describe(dict(config,ISA_C=1,MUA_BRANCH_PREDICTOR='bimodal',MUA_BTB='direct_mapped',
                        MUA_BTB_IDATA_HWORDS=6),contract='map_dse')
        f=b['external_models']['fetchModel']['parameters']
        self.assertEqual((f['predictor'],f['btb'],f['idata_hwords']),(2,True,6))
        self.assertTrue(f['static_not_taken']) # prediction enabled: no request hold
        self.assertEqual(b['coverage']['MUA_BTB_IDATA_HWORDS'],'reference_clocked_bpu_model')
        retained=describe(dict(config,MUA_DE_OPERAND_RETENTION=1),contract='map_dse')
        normal=describe(config,contract='map_dse')
        self.assertEqual(retained['id'],normal['id'])
        self.assertEqual(retained['coverage']['MUA_DE_OPERAND_RETENTION'],
                         'cycle_equivalent_in_supported_forwarding_profile')

    def test_independent_forwarding_and_retention_identity(self):
        from config_frontend import load_configurations
        from model import describe,render,FORWARD_PATHS
        config=load_configurations(['rv32im_dadda'],contract='map_dse')[0]['config']
        baseline=describe(config,contract='map_dse')
        identities={baseline['id']}
        for mask in range(15):
            c=dict(config,**{p:int(bool(mask&(1<<i))) for i,p in enumerate(FORWARD_PATHS)})
            d=describe(c,contract='map_dse');identities.add(d['id'])
            self.assertTrue(d['schedule']['fine_forwarding'])
            self.assertEqual([d['schedule'][p.removeprefix('MUA_').lower()] for p in FORWARD_PATHS],
                             [bool(mask&(1<<i)) for i in range(4)])
            self.assertNotIn('Da -> OperandWait',render(d))
            self.assertNotIn('{Xa, Xb} -> ALU',render(d))
            retained=describe(dict(c,MUA_DE_OPERAND_RETENTION=1),contract='map_dse')
            self.assertNotEqual(d['id'],retained['id'])
            self.assertEqual(retained['coverage']['MUA_DE_OPERAND_RETENTION'],'producer_window_retention')
            off=describe(dict(c,MUA_FORWARDING=0),contract='map_dse')
            off_ret=describe(dict(c,MUA_FORWARDING=0,MUA_DE_OPERAND_RETENTION=1),contract='map_dse')
            self.assertEqual(off['id'],off_ret['id'])
        self.assertEqual(len(identities),16)
        self.assertIn('Da -> OperandWait',render(baseline))
        self.assertEqual(UquMapping(True).edge_name(SimpleNamespace(isDynamic=lambda:True,name='AdmissionBase')),'EX_stage')

    def test_positive_delay_bias_preserves_zero_wait(self):
        graph=Graph();graph.add_edge('EX_stage_i','Admission',weight=0)
        root=SimpleNamespace()
        class Node:
            def getAllOutEdges(self):return []
            def getAllOutNodes(self):return []
        UquMapping(True).graph(graph,SimpleNamespace(getRootNode=lambda:Node()))
        self.assertEqual(graph.edges['EX_stage_i','Admission']['weight'],-1)
        self.assertEqual(graph.edges['IF_stage','Admission']['weight'],0)
        self.assertEqual(graph.edges['Serial_i','Admission']['weight'],0)

    def test_profile_rejects_stale_operands_and_unfinished_blocks(self):
        a=dict(pc=0x80000000,code=0x8082,typeId=66,rs1=1,rs2=0,rd=0)
        block=dict(startPc=a['pc'],endPc=a['pc'],instrs=[a])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'profile.json'
            good=dict(schema_version=2,blocks=[block])
            path.write_text(json.dumps(good));self.assertEqual(load_profile(path),good)
            for bad in (dict(schema_version=1,blocks=[block]),
                        dict(schema_version=2,blocks=[dict(block,endPc=0)]),
                        dict(schema_version=2,blocks=[dict(block,instrs=[dict(a,rd=32)])]),
                        dict(schema_version=2,blocks=[dict(block,instrs=[a,dict(a,rd=1)])])):
                path.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):load_profile(path)

    def test_mapping_rejects_unknown_connectors_and_stage_layout(self):
        mapping = UquMapping(True)
        with self.assertRaisesRegex(ValueError, 'connector'):
            mapping.edge_name(SimpleNamespace(isDynamic=lambda: True, name='Other'))
        self.assertEqual(mapping.edge_name(SimpleNamespace(isDynamic=lambda: True, name='Ld')), 'Xd')
        with self.assertRaisesRegex(ValueError, 'layout'):
            mapping.configure(None, SimpleNamespace(getAllTimingVariables=lambda: []))
        schedule = SimpleNamespace(getAllTimingVariables=lambda: [SimpleNamespace(name=s) for s in STAGES],
                                   getAllResourceModels=lambda: [SimpleNamespace(name='dynamic')])
        with self.assertRaisesRegex(ValueError, 'resource contract'):
            mapping.configure(None, schedule)

    def test_admission_and_committed_setter_semantics(self):
        for forwarding, load, extra in ((True, False, 0), (False, False, 1), (True, True, 1)):
            graph = Graph();graph.add_edge('Result', 'Xd_o', weight=3)
            edge = SimpleNamespace(isDynamic=lambda: True, name='Ld' if load else 'Xd')
            # Use a hashable node for the traversal.
            class Node:
                def getAllOutEdges(self): return [edge]
                def getAllOutNodes(self): return []
            root = Node()
            UquMapping(forwarding).graph(graph, SimpleNamespace(getRootNode=lambda: root))
            self.assertEqual(graph.edges['Result', 'UquAdmissionResult']['weight'],3)
            self.assertEqual(graph.edges['UquAdmissionResult','Admit_o']['weight'],extra)
            self.assertEqual(graph.edges['Committed_i', 'Committed_o']['weight'], 0)
            self.assertEqual(graph.edges['Enter', 'Entrance_o']['weight'], 0)

    def test_actual_upstream_blocks_shared_delays_and_small_dictionary(self):
        backend = ROOT/'build/deps/perfsim-upstream/etiss-perf-sim/etiss_plugins/SoftwareEvalLib/libs/backends'
        compiler, patch = shutil.which('c++'), shutil.which('patch')
        if not compiler or not patch or not (backend/'include/internal/MAPExplorer.h').is_file():
            self.skipTest('requires provisioned pinned MAPExplorer and a C++ compiler')
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for name in ('MAPExplorer.h', 'BlockSchedulingDictionary.h'):
                destination = folder/'include/internal'/name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(backend/'include/internal'/name, destination)
            patched = subprocess.run([patch, '-p1', '-i', str(ROOT/'verif/perfsim/patches/map-explorer-runtime.patch')],
                                     cwd=folder, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(patched.returncode, 0, patched.stdout)
            exe = folder/'runtime'
            built = subprocess.run([compiler, '-std=c++17', '-include', 'cstdint',
                '-I'+str(folder/'include/internal'), '-I'+str(backend/'include/internal'),
                '-I'+str(backend/'include/api/softwareEval-backends'), '-I'+str(backend/'libs/MAPModels/include'),
                str(ROOT/'verif/perfsim/tests/map_runtime.cpp'), '-o', str(exe)],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(built.returncode, 0, built.stdout)
            run = subprocess.run([str(exe)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(run.returncode, 0, run.stdout)

    def test_trace_models_and_de_branch_publication(self):
        backend=ROOT/'build/deps/perfsim-upstream/etiss-perf-sim/etiss_plugins/SoftwareEvalLib/libs/backends'
        if not shutil.which('c++') or not (backend/'src/internal/PerformanceModel.cpp').is_file():
            self.skipTest('requires a C++ compiler and pinned backend')
        with tempfile.TemporaryDirectory() as directory:
            exe=Path(directory)/'models'
            built=subprocess.run(['c++','-std=c++17','-include','cstdint',
                '-I'+str(ROOT/'verif/perfsim/models'),'-I'+str(backend/'include/internal'),
                '-I'+str(backend/'include/api/softwareEval-backends'),
                str(ROOT/'verif/perfsim/tests/trace_models.cpp'),str(backend/'src/internal/PerformanceModel.cpp'),'-o',str(exe)],
                text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            self.assertEqual(built.returncode,0,built.stdout)
            self.assertEqual(subprocess.run([str(exe)]).returncode,0)

    def test_upstream_composition_matches_numeric_instruction_products(self):
        original=ROOT/'build/deps/perfsim-upstream/code_gen/generators/M2-ISA-R-Perf'
        python=ROOT/'build/perfsim-tools/model-python/bin/python'
        if not python.is_file() or not original.is_dir() or not shutil.which('c++'):
            self.skipTest('requires provisioned generator Python and C++')
        sys.path.insert(0,str(ROOT/'verif/sim/common'))
        from config_frontend import load_configurations
        from model import render,describe
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);generator=folder/'generator'
            shutil.copytree(original,generator,ignore=shutil.ignore_patterns('__pycache__'))
            for patch in ('m2isar-perf-branch-identity.patch','m2isar-perf-map-mapping.patch','m2isar-perf-map-algebra.patch'):
                subprocess.run(['patch','-p1','-i',str(ROOT/'verif/perfsim/patches'/patch)],cwd=generator,
                               check=True,stdout=subprocess.PIPE)
            dsl=folder/'model.corePerfDsl'
            config=load_configurations(['rv32im_dadda'],contract='map_dse')[0]['config']
            for change in ({},{'MUA_FORWARD_MEM_TO_DE':0},{'MUA_FORWARDING':0}):
                dsl.write_text(render(describe(dict(config,**change),contract='map_dse')))
                run=subprocess.run([str(python),str(ROOT/'verif/perfsim/tests/map_algebra.py'),str(generator),str(dsl),str(folder)],
                                   text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
                self.assertEqual(run.returncode,0,run.stdout)


if __name__ == '__main__': unittest.main()
