"""Exercise reference mismatch detection independently of processor simulation."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import spike
from component_runner import check_reference, check_results
from elf_image import ELFImage, Segment
from test_rvfi_trace import instruction


class SpikeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name)
        self.image = ELFImage(0x80000000, 0, (Segment(0x80000000, b'\0'*64, 64, 7),), {'tohost': 0x80000020})
        self.config = dict(ISA_E=0, ISA_C=0, ISA_M=0, ISA_UMODE=1, ISA_ZIFENCEI=0)

    def commit(self, pc, insn, registers=None, memory=None, csrs=None):
        return dict(hart=5, mode=3, pc=pc, insn=insn, registers=registers or {},
                    memory=memory or [], csrs=csrs or {})

    def fixture(self):
        pc = self.image.entry
        rows = [instruction(0, pc, insn=0x00100093, rd_addr=1, rd_wdata=1),
                instruction(1, pc+4, insn=0x00102023, rs2_addr=1, rs2_rdata=1,
                            mem_addr=pc+32, mem_wmask=15, mem_wdata=1),
                instruction(2, pc+8, insn=0x00002103, rd_addr=2, rd_wdata=1,
                            mem_addr=pc+32, mem_rmask=15, mem_rdata=1)]
        refs = [self.commit(0x1000+4*n, op) for n, op in enumerate(spike.BOOT_INSNS)]
        refs += [self.commit(pc, 0x00100093, {1: 1}),
                 self.commit(pc+4, 0x00102023, memory=[dict(address=pc+32, value=1, size=4)]),
                 self.commit(pc+8, 0x00002103, {2: 1}, [dict(address=pc+32, value=None, size=None)]),
                 self.commit(pc+12, 0x13)]
        return rows, refs

    def test_independent_store_load_and_lookahead(self):
        rows, refs = self.fixture()
        self.assertEqual(spike.compare(rows, refs, self.image), 3)
        for index, field, value in ((0, 'rvfi_insn', 0x13), (0, 'rvfi_rd_wdata', 2),
                (0, 'rvfi_pc_rdata', 4), (2, 'rvfi_pc_wdata', 0),
                (1, 'rvfi_rs2_rdata', 2), (1, 'rvfi_mem_addr', 0),
                (1, 'rvfi_rs2_addr', 2),
                (1, 'rvfi_mem_wmask', 3), (1, 'rvfi_mem_wdata', 2),
                (2, 'rvfi_mem_rdata', 2), (2, 'rvfi_mem_rmask', 1)):
            corrupted = deepcopy(rows)
            corrupted[index][field] = value
            with self.subTest(field=field), self.assertRaises(spike.Mismatch):
                spike.compare(corrupted, refs, self.image)
        with self.assertRaises(spike.Mismatch): spike.compare(rows, refs[:-1], self.image)
        refs[0]['insn'] = 0
        with self.assertRaises(spike.Mismatch): spike.compare(rows, refs, self.image)

    def test_csr_channels_checked_against_reference_effect_and_prestate(self):
        pc = self.image.entry
        row = instruction(0, pc, insn=0x30505073)
        row['csrs'] = {'mtvec': dict(rmask=0, wmask=spike.MASK, rdata=0, wdata=0)}
        refs = [self.commit(0x1000+4*n, op) for n, op in enumerate(spike.BOOT_INSNS)]
        refs += [self.commit(pc, row['rvfi_insn'], csrs={0x305: 0}), self.commit(pc+4, 0x13)]
        self.assertEqual(spike.compare([row], refs, self.image), 1)
        row['csrs']['mtvec']['wdata'] = 4
        with self.assertRaisesRegex(spike.Mismatch, 'csr_write'): spike.compare([row], refs, self.image)
        row['csrs']['mtvec'].update(wdata=0, rmask=spike.MASK)
        with self.assertRaisesRegex(spike.Mismatch, 'csr_rmask'): spike.compare([row], refs, self.image)

    def test_commit_parser_handles_compressed_csr_and_byte_store(self):
        path = self.path / 'spike.log'
        path.write_text('core   5: 0x80000000 (0x0085) addi ra, ra, 1\n'
                        'core   5: 3 0x80000000 (0x0085) x1  0x00000001\n'
                        'core   5: 3 0x80000002 (0x30509073) c773_mtvec 0x80000000\n'
                        'core   5: 3 0x80000006 (0x00100023) mem 0x80000021 0xaa\n')
        refs = spike.parse_commits(path)
        self.assertEqual(refs[0]['insn'], 0x85)
        self.assertEqual(refs[1]['csrs'], {0x305: 0x80000000})
        self.assertEqual(refs[2]['memory'], [dict(address=0x80000021, value=0xaa, size=1)])
        for line in ('core   5: exception trap_illegal_instruction',
                     'core   5: 3 0x80000000 (0x13) f1 0x12345678', '',
                     'core   5: 3 0x80000000 (0x13) x1 0x1 x1 0x2'):
            path.write_text(line)
            with self.subTest(line=line), self.assertRaises(ValueError): spike.parse_commits(path)

    def test_memory_widths_independent_of_rvfi(self):
        for insn, expected in ((0x00000003, ('load', 1)), (0x00001003, ('load', 2)),
                (0x00002023, ('store', 4)), (0x4000, ('load', 4)),
                (0xc002, ('store', 4)), (0x13, (None, 0))):
            self.assertEqual(spike.memory_operation(insn), expected)

    def test_unsupported_events_are_rejected_not_skipped(self):
        reset = dict(type='reset', epoch=0)
        for records in ([reset, instruction(trap=1)], [reset, dict(type='interrupt')],
                [reset, instruction(insn=0xc0002573)], [reset, instruction(insn=0x30200073)],
                [reset, reset, instruction()], [reset]):
            with self.subTest(records=records), self.assertRaises(ValueError):
                spike.validate_profile(records, self.config, self.image)
        with self.assertRaisesRegex(ValueError, 'PMP'):
            spike.validate_profile([reset, instruction()], dict(self.config, ISA_PMP=1), self.image)

    def test_discovery_precedence_and_qualification(self):
        directory = self.path / 'bin'
        directory.mkdir()
        executable = directory / 'spike'
        executable.write_text('#!/bin/sh\nexit 0\n')
        executable.chmod(0o755)
        env = dict(PATH='', RISCV=str(self.path))
        self.assertEqual(spike.discover_spike(environ=env), str(executable))
        with self.assertRaises(ValueError): spike.discover_spike('missing', env)
        with patch.object(spike.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'wrong version')):
            with self.assertRaisesRegex(ValueError, 'binary pin'): spike.identify_spike(str(executable))

    def test_process_timeout_preserves_failed_evidence(self):
        (self.path / 'program.elf').write_bytes(b'ELF')
        info = dict(profile='test', executable='/external/spike')
        reset = dict(type='reset', epoch=0)
        with patch.object(spike, 'load_elf', return_value=self.image), \
             patch.object(spike, 'read_trace', return_value=[reset, instruction(0, self.image.entry)]), \
             patch.object(spike.subprocess, 'run', side_effect=subprocess.TimeoutExpired('spike', 1)):
            with self.assertRaises(subprocess.TimeoutExpired): spike.check_run(self.path, self.config, info, timeout=1)
        self.assertEqual(json.loads((self.path / 'spike.json').read_text())['status'], 'failed')
        self.assertTrue((self.path / 'spike-process.log').is_file())

    def test_mismatch_records_both_observations_and_fails_successful_junit(self):
        rows, refs = self.fixture()
        rows[0]['rvfi_rd_wdata'] = 99
        (self.path / 'program.elf').write_bytes(b'ELF')
        (self.path / 'results.xml').write_text('<testsuites><testsuite><testcase name="execute"/></testsuite></testsuites>')
        (self.path / 'rvfi.jsonl').write_text('\n'.join(json.dumps(row) for row in
            [dict(type='reset', epoch=0), *rows]) + '\n')
        info = dict(profile='test', executable='/external/spike')
        with patch.object(spike, 'load_elf', return_value=self.image), \
             patch.object(spike, 'parse_commits', return_value=refs), \
             patch.object(spike.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
            with self.assertRaisesRegex(spike.Mismatch, 'gpr_write'):
                check_reference(self.path, self.config, info)
        data = json.loads((self.path / 'spike.json').read_text())
        self.assertEqual(data['status'], 'failed')
        self.assertEqual(data['mismatch']['index'], 0)
        self.assertEqual(data['rvfi_observation']['rvfi_rd_wdata'], 99)
        self.assertEqual(data['spike_observation']['registers'], {'1': 1})
        with self.assertRaisesRegex(RuntimeError, 'failed or skipped'):
            check_results(self.path / 'results.xml', ['execute'])
