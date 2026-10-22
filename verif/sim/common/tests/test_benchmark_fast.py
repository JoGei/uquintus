"""Native benchmark serialization, reduced dependencies and mode selection."""
from pathlib import Path
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import benchmark
from benchmark_fast import read_memory, write_memory
from elf_image import ELFImage, Segment


class FastBenchmarkTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('UQU_FAST_NATIVE'), 'set UQU_FAST_NATIVE to a compiled RV32I benchmark driver')
    def test_native_driver_latencies_completion_and_failure_paths(self):
        # A tiny RV32I program: time a dependent store/load, compute zero on
        # success, then report through tohost. No compiler or C library needed.
        words = [0xb00022f3,  # csrr x5,mcycle (start)
                 0x80000337,  # lui x6,0x80000
                 0x10030313,  # addi x6,x6,256
                 0x02a00393,  # addi x7,x0,42
                 0x00732023,  # sw x7,0(x6)
                 0x00032403,  # lw x8,0(x6)
                 0x0083c4b3,  # xor x9,x7,x8
                 0xb0002573,  # csrr x10,mcycle (stop)
                 0x00149493,  # slli x9,x9,1
                 0x0014e493,  # ori x9,x9,1
                 0x00932423,  # sw x9,8(x6) (tohost)
                 0x0000006f]  # j .
        executable = str(Path(os.environ['UQU_FAST_NATIVE']).resolve())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def execute(label, imem=1, dmem=1, limit=10000, instructions=None):
                directory = root / label
                directory.mkdir()
                data = struct.pack('<12I', *(words if instructions is None else instructions))
                image = ELFImage(0x80000000, 0, (Segment(0x80000000, data, 512, 7),), {})
                write_memory(image, directory / 'image.bin')
                result = subprocess.run([executable, 'image.bin', str(limit),
                    str(image.entry), str(imem), str(dmem), str(0x80000108), str(image.entry),
                    str(image.entry+28)], cwd=directory, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                return result, json.loads((directory / 'native.json').read_text()), directory
            durations = []
            for name, imem, dmem in [('base',1,1), ('repeat',1,1), ('if_slow',3,1), ('data_slow',1,3), ('both_slow',3,3)]:
                result, record, directory = execute(name, imem, dmem)
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertEqual(record['status'], 'passed')
                self.assertEqual(read_memory(directory / 'final-memory.bin')[0x80000100], 42)
                self.assertEqual(record['stop']['cycle']-record['start']['cycle'],
                                 record['stop']['mcycle_low']-record['start']['mcycle_low'])
                durations.append(record['cycles'])
            self.assertEqual(durations[0], durations[1])
            self.assertGreater(durations[2], durations[0])
            self.assertGreater(durations[3], durations[0])
            self.assertGreater(durations[4], max(durations[2:4]))
            failure = list(words)
            failure[9] = 0x00f06493  # ori x9,x0,15 -> software failure 7
            illegal = list(words)
            illegal[0] = 0xffffffff
            for label, options, diagnostic in [('watchdog',dict(limit=2),'watchdog'),
                    ('software_failure',dict(instructions=failure),'software reported failure 7'),
                    ('illegal',dict(instructions=illegal),'unexpected trap')]:
                result, record, _ = execute(label, **options)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(record['status'], 'failed')
                self.assertIn(diagnostic, record['detail'])

    def test_memory_image_round_trip_keeps_addresses_bytes_and_bss(self):
        image = ELFImage(0x80000000, 0, (
            Segment(0x80000000, b'\x13\0\0\0', 8, 5),
            Segment(0x80001000, b'\x7f\x80\xff', 5, 6)), {})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'memory.bin'
            write_memory(image, path)
            self.assertEqual(read_memory(path), image.memory())
            valid = path.read_bytes()
            overlap = b'UQUMEM01'+struct.pack('<I', 2)+struct.pack('<III', 0x1000, 1, 1)+b'x'
            overlap += struct.pack('<III', 0x1000, 1, 1)+b'y'
            for bad in (valid[:11], valid[:-1], valid+b'x', overlap,
                        b'UQUMEM01'+struct.pack('<I', 5000)):
                path.write_bytes(bad)
                with self.subTest(data=bad), self.assertRaises(ValueError): read_memory(path)

    def test_fast_mode_rejects_verification_options_explicitly(self):
        for kw in ({'waves': 1}, {'reference': 'spike'}):
            with self.subTest(options=kw), self.assertRaisesRegex(ValueError, 'BENCHMARK_MODE=checked'):
                benchmark.run('coremark', 'rv32i', mode='fast', **kw)

    def test_fast_adapter_imports_without_cocotb_or_pyuvm(self):
        directory = Path(__file__).resolve().parents[1]
        script = '''
import sys, importlib.abc
class BlockVerification(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('cocotb','pyuvm'):
            raise ImportError('verification package deliberately unavailable')
sys.meta_path.insert(0,BlockVerification())
import benchmark_fast
assert 'cocotb' not in sys.modules and 'pyuvm' not in sys.modules
'''
        subprocess.run([sys.executable, '-c', script], cwd=directory, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
