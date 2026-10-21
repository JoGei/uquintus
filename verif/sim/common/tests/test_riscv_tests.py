"""Pinned archive integrity, applicability, suite validation and failure handling."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import elf_suite
import riscv_tests


class RiscvTestsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = dict(ISA_E=0, ISA_M=0, ISA_C=0, ISA_ZIFENCEI=0)

    def archive(self, extra=None):
        path = self.root / 'source.tar.gz'
        revision = 'a' * 40
        with tarfile.open(path, 'w:gz') as output:
            for filename, content in [('isa/rv32ui/simple.S', b'source'), ('LICENSE', b'license')]:
                entry = tarfile.TarInfo('riscv-tests-' + revision + '/' + filename)
                entry.size = len(content)
                output.addfile(entry, io.BytesIO(content))
            if extra:
                output.addfile(extra)
        return path, dict(revision=revision, archive_sha256=hashlib.sha256(path.read_bytes()).hexdigest())

    def test_archive_is_pinned_and_modified_cache_is_rejected(self):
        path, lock = self.archive()
        with patch.object(riscv_tests, 'ROOT', self.root), patch.object(riscv_tests, 'load_lock', return_value=lock):
            destination = riscv_tests.fetch(path)
            self.assertFalse((destination / 'env').exists())
            self.assertFalse((destination / '.git').exists())
            riscv_tests.verify_sources(destination, lock)
            (destination / 'isa/rv32ui/simple.S').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'cached source changed'):
                riscv_tests.verify_sources(destination, lock)
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            riscv_tests.extract_archive(path, self.root, dict(lock, archive_sha256='0' * 64))

    def test_archive_does_not_accept_escaping_paths_or_isa_links(self):
        for name in ('riscv-tests-' + 'a' * 40 + '/../outside',
                     'riscv-tests-' + 'a' * 40 + '/isa/link'):
            entry = tarfile.TarInfo(name)
            entry.type = tarfile.SYMTYPE
            entry.linkname = '/outside'
            path, lock = self.archive(entry)
            with self.assertRaisesRegex(ValueError, 'path/link|unexpected link'):
                riscv_tests.extract_archive(path, self.root, lock)

    def test_applicability_is_explicit_and_requested_exclusions_fail(self):
        for group, names in [('rv32ui', 'simple ma_data fence_i'), ('rv32um', 'mul'), ('rv32uc', 'rvc')]:
            directory = self.root / 'isa' / group
            directory.mkdir(parents=True)
            (directory / 'Makefrag').write_text(f'{group}_sc_tests = \\\n  {names}\n{group}_p_tests = ignored\n')
        tests, excluded = riscv_tests.select_tests(self.root, self.config)
        self.assertEqual([t['name'] for t in tests], ['rv32ui-p-simple'])
        self.assertEqual(len(excluded), 4)
        config = dict(self.config, ISA_M=1, ISA_C=1, ISA_ZIFENCEI=1)
        self.assertEqual(len(riscv_tests.select_tests(self.root, config)[0]), 4)
        for selection in ('rv32ui-p-ma_data', 'rv32um-p-mul', 'unknown'):
            with self.assertRaises(ValueError):
                riscv_tests.select_tests(self.root, self.config, selection)
        with self.assertRaisesRegex(ValueError, 'RV32E'):
            riscv_tests.select_tests(self.root, dict(self.config, ISA_E=1))

    def manifest(self):
        programs = []
        for name in ('first', 'bad', 'last'):
            path = self.root / (name + '.elf')
            path.write_bytes(b'fixture')
            programs.append(dict(name=name, path=str(path), sha256=hashlib.sha256(b'fixture').hexdigest()))
        data = dict(schema_version=1, suite='riscv-tests', status='passed', parameters=self.config,
                    programs=programs, selection='all', upstream=dict(revision='a'*40),
                    compiler_info=dict(family='gcc', version='14.2.0', march='rv32i_zicsr', abi='ilp32'),
                    excluded=[dict(name='not-supported', reason='feature disabled')])
        path = self.root / 'suite.json'
        path.write_text(json.dumps(data))
        return path

    def test_suite_rejects_changed_elf_and_mismatched_configuration(self):
        path = self.manifest()
        with patch.object(elf_suite, 'load_elf'):
            elf_suite.validate_suite(path, self.config)
            with self.assertRaisesRegex(ValueError, 'matching full configuration'):
                elf_suite.validate_suite(path, dict(self.config, ISA_M=1))
            (self.root / 'first.elf').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'ELF changed'):
                elf_suite.validate_suite(path, self.config)

    def test_batch_continues_after_failure_and_preserves_independent_results(self):
        path = self.manifest()
        visited = []

        def execute(arguments, shared_build):
            name = arguments[arguments.index('--label') + 1]
            visited.append(name)
            if name == 'bad':
                raise RuntimeError('deliberate fixture failure')
            return self.root / name

        with patch.object(elf_suite, 'load_elf'), patch.object(elf_suite, 'run_component', side_effect=execute):
            with self.assertRaisesRegex(RuntimeError, '1 riscv-tests failed: bad'):
                elf_suite.run_suite(path, self.root / 'rv32i.yml', self.config, root=self.root)
        self.assertEqual(visited, ['first', 'bad', 'last'])
        report = next((self.root / 'build').rglob('report.json'))
        data = json.loads(report.read_text())
        self.assertEqual(data['status'], 'failed')
        cases = ET.parse(report.parent / 'suite-results.xml').findall('.//testcase')
        self.assertEqual(len(cases), 4)
        self.assertEqual(sum(c.find('failure') is not None for c in cases), 1)
        self.assertEqual(sum(c.find('skipped') is not None for c in cases), 1)
