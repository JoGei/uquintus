"""Fail-closed Embench selection, source coverage and self-check evidence."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import benchmark
from benchmark_measure import benchmark_result
from embench import verify_manifest
from pinned_archive import fetch, load_lock, verify_sources


class EmbenchTests(unittest.TestCase):
    def test_self_check_requires_verified_work_and_independent_cycle_agreement(self):
        metadata = dict(validator='embench', profile='crc32', iterations=1,
                        local_scale_factor=170, workload_scale=1, warmup_heat=1, arithmetic='integer')
        text = ('Embench workload: crc32\nIterations: 1\nLocal scale: 170\n'
                'Workload scale: 1\nWarmup: 1\nVerified: 1\nCycles: 123\n')
        result = benchmark_result(text, metadata, 123)
        self.assertEqual(result['cycles_per_iteration'], 123)
        self.assertFalse(result['official_score'])
        for bad in (text.replace('Verified: 1', 'Verified: 0'),
                    text.replace('Verified: 1', 'Verified: 4294967295'),
                    text.replace('crc32', 'ud'), text.replace('170', '171'),
                    text.replace('Warmup: 1', 'Warmup: 0'), text.replace('123', '124'),
                    text + 'Verified: 1\n', ''):
            with self.subTest(text=bad), self.assertRaisesRegex(ValueError, 'Embench self-check'):
                benchmark_result(bad, metadata, 123)

    def test_subset_selection_is_explicit_and_cannot_escape_port_directory(self):
        _, data, _ = benchmark.settings('embench/embench-iot')
        self.assertEqual(len(benchmark.selected_profiles(data, 'all')), 19)
        self.assertEqual(benchmark.selected_profiles(data, 'crc32,ud'), ['crc32', 'ud'])
        for selection in ('crc32,crc32', 'crc32,typo', '', '../crc32'):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                benchmark.selected_profiles(data, selection)
        for name in ('../embench-iot', 'embench/../embench-iot', '/embench-iot'):
            with self.subTest(name=name), self.assertRaises(ValueError): benchmark.settings(name)

    def test_manifest_rejects_omitted_workloads_sources_and_changed_repeat_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            directory = source / 'src/crc32'
            directory.mkdir(parents=True)
            c_file = directory / 'crc_32.c'
            c_file.write_text('#define LOCAL_SCALE_FACTOR 170\n')
            data = dict(profiles={'crc32': dict(sources=['src/crc32/crc_32.c'], local_scale_factor=170)})
            verify_manifest(source, data)
            c_file.write_text('#define LOCAL_SCALE_FACTOR 171\n')
            with self.assertRaisesRegex(ValueError, 'scale'): verify_manifest(source, data)
            c_file.write_text('#define LOCAL_SCALE_FACTOR 170\n')
            (directory / 'missing.c').write_text('')
            with self.assertRaisesRegex(ValueError, 'sources'): verify_manifest(source, data)
            (source / 'src/ud').mkdir()
            with self.assertRaisesRegex(ValueError, 'every'): verify_manifest(source, data)

    def test_invalid_workload_or_memory_settings_are_rejected(self):
        port, data, _ = benchmark.settings('embench/embench-iot')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / 'verif/sw/benchmark/embench/embench-iot'
            fixture.mkdir(parents=True)
            (fixture / 'lock.json').write_text((port / 'lock.json').read_text())
            for changed in (dict(data, defines=dict(CPU_MHZ=0, WARMUP_HEAT=1)),
                            dict(data, memory=dict(imem_latency=0, dmem_latency=1)),
                            dict(data, profiles={'../escape': data['profiles']['crc32']}),
                            dict(data, profiles={'crc32': dict(data['profiles']['crc32'], sources=['../escape.c'])})):
                (fixture / 'config.yml').write_text(yaml.safe_dump(changed))
                with patch.object(benchmark, 'ROOT', root), self.assertRaises(ValueError):
                    benchmark.settings('embench/embench-iot')

    def test_pinned_unused_symlink_is_omitted_but_other_links_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prefix = 'embench-iot-' + 'a' * 40
            archive = root / 'source.tar.gz'
            with tarfile.open(archive, 'w:gz') as output:
                entry = tarfile.TarInfo(prefix + '/src/crc32.c')
                entry.size = 1
                output.addfile(entry, io.BytesIO(b'x'))
                entry = tarfile.TarInfo(prefix + '/config/native/chips/default')
                entry.type, entry.linkname = tarfile.SYMTYPE, 'speed-test-gcc'
                output.addfile(entry)
            lock = dict(schema_version=1, name='embench-iot', revision='a' * 40,
                        archive_url='https://example.org/source.tar.gz',
                        archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                        exclude_paths=['config/native/chips/default'])
            path = root / 'lock.json'
            path.write_text(json.dumps(lock))
            load_lock(path)
            directory = fetch(root / 'cache', lock, archive)
            verify_sources(directory, lock)
            self.assertFalse((directory / 'config/native/chips/default').exists())
            self.assertEqual((directory / 'src/crc32.c').read_text(), 'x')
            with self.assertRaisesRegex(ValueError, 'path/link'):
                fetch(root / 'no_exclusion', dict(lock, exclude_paths=[]), archive)
            with self.assertRaisesRegex(ValueError, 'do not match'):
                fetch(root / 'wrong_exclusion', dict(lock, exclude_paths=[*lock['exclude_paths'], 'missing']), archive)
            path.write_text(json.dumps(dict(lock, exclude_paths=['../escape'])))
            with self.assertRaisesRegex(ValueError, 'exclusions'): load_lock(path)
