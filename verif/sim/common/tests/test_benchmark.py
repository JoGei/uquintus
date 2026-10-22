"""Benchmark measurements must reject stale inputs, bad CRCs and invalid windows."""
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import benchmark
from benchmark_measure import BenchmarkWindow, coremark_result, marker_addresses, read_log, software_compatible
from elf_image import ELFImage, Segment
from pinned_archive import fetch, verify_sources


class BenchmarkTests(unittest.TestCase):
    def test_identical_elf_can_be_reused_only_across_microarchitecture_changes(self):
        built = dict(HART_ID=0, ISA_E=0, ISA_M=0, MUA_BRANCH_PREDICTOR='none')
        self.assertTrue(software_compatible(built, dict(built, MUA_BRANCH_PREDICTOR='static_not_taken')))
        self.assertFalse(software_compatible(built, dict(built, ISA_M=1)))
        self.assertFalse(software_compatible(built, dict(built, HART_ID=5)))

    def image(self):
        return ELFImage(0x80000000, 0, (Segment(0x80000000,
            struct.pack('<II', 0xb0002573, 0xb00025f3), 8, 5),),
            dict(uqu_bench_start=0x80000000, uqu_bench_stop=0x80000004))

    def test_window_uses_retirement_edges_and_checks_software_cycle_delta(self):
        window = BenchmarkWindow(self.image())
        window.retire(0x80000000, 10, 3, 0xfffffff0, 0)
        window.retire(0x80000004, 46, 13, 0x14, 0)
        self.assertEqual(window.finish()['cycles'], 36)
        self.assertEqual(window.finish()['cpi'], 3.6)
        window.stop['mcycle_low'] += 1
        with self.assertRaisesRegex(ValueError, 'disagrees'):
            window.finish()

    def test_missing_repeated_reordered_and_inhibited_markers_fail(self):
        for action in ('missing', 'stop_first', 'repeat_start', 'repeat_stop', 'inhibit'):
            window = BenchmarkWindow(self.image())
            with self.subTest(action=action), self.assertRaises(ValueError):
                if action == 'missing': window.finish()
                if action == 'stop_first': window.retire(window.stop_pc, 10, 3, 10, 0)
                window.retire(window.start_pc, 10, 3, 10, 0)
                if action == 'repeat_start': window.retire(window.start_pc, 11, 4, 11, 0)
                if action == 'inhibit': window.retire(0x1234, 11, 4, 0, 1)
                window.retire(window.stop_pc, 20, 8, 20, 0)
                if action == 'repeat_stop': window.retire(window.stop_pc, 21, 9, 21, 0)
        image = self.image()
        for symbols in ({}, dict(image.symbols, uqu_bench_start=0x80000001),
                        dict(image.symbols, uqu_bench_stop=image.symbols['uqu_bench_start'])):
            with self.assertRaises(ValueError):
                marker_addresses(ELFImage(image.entry, 0, image.segments, symbols))
        bad = ELFImage(image.entry, 0, (Segment(image.entry, b'\x13\0\0\0'*2, 8, 5),), image.symbols)
        with self.assertRaisesRegex(ValueError, 'read of mcycle'): marker_addresses(bad)

    def log(self, profile='performance'):
        values = ('e9f5', 'e714', '1fd7', '8e3a') if profile == 'performance' else ('18f2', 'e3c1', '0747', '8d84')
        return ('CoreMark Size    : 666\nTotal ticks      : 120\nIterations       : 1\n'
                f'seedcrc          : 0x{values[0]}\n[0]crclist       : 0x{values[1]}\n'
                f'[0]crcmatrix     : 0x{values[2]}\n[0]crcstate      : 0x{values[3]}\n'
                '[0]crcfinal      : 0x1234\n'
                'ERROR! Must execute for at least 10 secs for a valid result!\nErrors detected\n')

    def test_crc_validation_is_independent_of_upstream_zero_exit_code(self):
        for profile in ('performance', 'validation'):
            result = coremark_result(self.log(profile), profile, 1, 120)
            self.assertFalse(result['official_score'])
            self.assertEqual(result['cycles_per_iteration'], 120)
        for text in (self.log().replace('e714', '0000'), self.log().replace('120', '121'),
                     self.log().replace('Iterations       : 1', 'Iterations       : 2'),
                     self.log().replace('666', '667'), self.log() + 'ERROR! data types\n',
                     self.log() + 'seedcrc          : 0xe9f5\n',
                     self.log().replace('Errors detected', 'Correct operation validated')):
            with self.subTest(text=text), self.assertRaises(ValueError):
                coremark_result(text, 'performance', 1, 120)

    def test_ram_log_rejects_truncation_and_unsupported_output(self):
        image = ELFImage(0, 0, (), dict(uqu_bench_log=0x100, uqu_bench_log_size=0x200,
                                       uqu_bench_log_overflow=0x204))
        memory = {0x100: ord('x'), 0x200: 1}
        self.assertEqual(read_log(image, memory), 'x')
        memory[0x204] = 1
        with self.assertRaisesRegex(ValueError, 'overflow'): read_log(image, memory)

    def test_pinned_archive_rejects_tampering_links_and_escaping_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for extra in (None, '../outside', 'link'):
                archive = root / 'source.tar.gz'
                prefix = 'coremark-' + 'a'*40
                with tarfile.open(archive, 'w:gz') as output:
                    entry = tarfile.TarInfo(prefix + '/core_main.c')
                    entry.size = 6
                    output.addfile(entry, io.BytesIO(b'source'))
                    if extra:
                        entry = tarfile.TarInfo(prefix + '/' + extra)
                        entry.type, entry.linkname = tarfile.SYMTYPE, '/outside'
                        output.addfile(entry)
                lock = dict(name='coremark', revision='a'*40, archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
                if extra:
                    with self.assertRaisesRegex(ValueError, 'path/link'): fetch(root / extra.replace('/', '_'), lock, archive)
                else:
                    cache = root / 'cache'
                    directory = fetch(cache, lock, archive)
                    verify_sources(directory, lock)
                    self.assertEqual(fetch(cache, lock), directory)
                    (directory / 'core_main.c').write_text('modified')
                    with self.assertRaisesRegex(ValueError, 'source changed'): verify_sources(directory, lock)
                    with self.assertRaisesRegex(ValueError, 'SHA-256'):
                        fetch(root / 'bad_checksum', dict(lock, archive_sha256='0'*64), archive)

    def test_settings_require_valid_workloads_and_memory_timing(self):
        port, data, _ = benchmark.settings('coremark')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / 'verif/sw/benchmark/coremark'
            fixture.mkdir(parents=True)
            (fixture / 'lock.json').write_text((port / 'lock.json').read_text())
            for changed in (dict(data, max_cycles=0), dict(data, memory=dict(imem_latency=0, dmem_latency=1)),
                            dict(data, defines=dict(ITERATIONS=0, TOTAL_DATA_SIZE=2000))):
                (fixture / 'config.yml').write_text(yaml.safe_dump(changed))
                with patch.object(benchmark, 'ROOT', root), self.assertRaises(ValueError):
                    benchmark.settings('coremark')

    def test_stale_build_cannot_run_and_profile_failure_does_not_hide_other_profile(self):
        _, settings, lock = benchmark.settings('coremark')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'build/uquintus-test/sw/benchmark/coremark/suite.json'
            path.parent.mkdir(parents=True)
            elf = root / 'test.elf'
            elf.write_bytes(b'fixture')
            suite = dict(status='passed', parameters={}, settings=settings, upstream=lock,
                         programs=[dict(profile=p, path=str(elf), sha256=benchmark.sha(elf))
                                   for p in settings['profiles']])
            path.write_text(json.dumps(suite))
            calls = []
            def execute(argv, shared_build):
                label = argv[argv.index('--label') + 1]
                calls.append(label)
                if label.endswith('performance'): raise RuntimeError('fixture failed')
            with patch.object(benchmark, 'ROOT', root), patch.object(benchmark, 'hardware', return_value=(root / 'test.yml', {})), \
                    patch.object(benchmark, 'settings', return_value=(None, settings, lock)), \
                    patch('component_runner.main', side_effect=execute):
                with self.assertRaisesRegex(RuntimeError, 'performance'): benchmark.run('coremark', 'test', mode='checked')
                self.assertEqual(calls, ['coremark-performance', 'coremark-validation'])
                path.write_text(json.dumps(dict(suite, settings={})))
                with self.assertRaisesRegex(ValueError, 'stale'): benchmark.run('coremark', 'test', mode='checked')
