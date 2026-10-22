"""External compiler discovery and target/family/version identification."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from toolchain import compiler_command, discover_compiler, identify_compiler, isa_abi


class ToolchainTests(unittest.TestCase):
    def test_isa_and_abi_are_derived_from_config(self):
        self.assertEqual(isa_abi(dict(ISA_E=0, ISA_M=1, ISA_C=1, ISA_ZIFENCEI=1)),
                         ('rv32imc_zicsr_zifencei', 'ilp32'))
        self.assertEqual(isa_abi(dict(ISA_E=1, ISA_M=0, ISA_C=0, ISA_ZIFENCEI=0)),
                         ('rv32e_zicsr', 'ilp32e'))

    def test_explicit_then_riscv_root_then_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'toolchain/bin').mkdir(parents=True)
            (root / 'path').mkdir()
            explicit = root / 'chosen'
            installed = root / 'toolchain/bin/riscv64-unknown-elf-gcc'
            fallback = root / 'path/clang'
            for path in (explicit, installed, fallback):
                path.write_text('#!/bin/sh\nexit 0\n')
                path.chmod(0o755)
            env = dict(PATH=str(root / 'path'), RISCV=str(root / 'toolchain'))
            self.assertEqual(discover_compiler(str(explicit), env), str(explicit))
            self.assertEqual(discover_compiler(environ=env), str(installed))
            self.assertEqual(discover_compiler(environ={'PATH': env['PATH']}), str(fallback))
            with self.assertRaisesRegex(ValueError, 'compiler not found'):
                discover_compiler('missing-explicit-compiler', env)

    def test_xpack_compiler_name_in_riscv_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'bin'
            directory.mkdir()
            compiler = directory / 'riscv-none-elf-gcc'
            compiler.write_text('#!/bin/sh\nexit 0\n')
            compiler.chmod(0o755)
            self.assertEqual(discover_compiler(environ=dict(RISCV=temporary, PATH='')), str(compiler))

    def test_clang_and_gcc_versions_come_from_macros_and_target_probe(self):
        config = dict(ISA_E=0, ISA_M=0, ISA_C=0, ISA_ZIFENCEI=0)
        for family, macros, banner, expected in (
            ('clang', '#define __clang__ 1\n#define __clang_major__ 18\n#define __clang_minor__ 1\n#define __clang_patchlevel__ 3\n#define __GNUC__ 4\n',
             'Ubuntu clang version 18.1.3', '18.1.3'),
            ('gcc', '#define __GNUC__ 14\n#define __GNUC_MINOR__ 2\n#define __GNUC_PATCHLEVEL__ 0\n',
             'RISC-V toolchain (GCC) 14.2.0', '14.2.0')):
            result = subprocess.CompletedProcess([], 0, '#define __riscv_xlen 32\n' + macros, '')
            with self.subTest(family=family), patch('toolchain.subprocess.check_output', side_effect=[banner, 'riscv32-unknown-elf']), patch('toolchain.subprocess.run', return_value=result) as probe:
                info = identify_compiler('/external/compiler', config)
                self.assertEqual((info['family'], info['version'], info['target']), (family, expected, 'riscv32-unknown-elf'))
                self.assertIn('-march=rv32i_zicsr', probe.call_args.args[0])
                self.assertEqual('-fuse-ld=lld' in compiler_command(info), family == 'clang')

    def test_host_or_unsupported_compiler_fails_explicitly(self):
        config = dict(ISA_E=0, ISA_M=0, ISA_C=0, ISA_ZIFENCEI=0)
        for result in (subprocess.CompletedProcess([], 1, '', 'unsupported target'),
                       subprocess.CompletedProcess([], 0, '#define __riscv_xlen 64\n', '')):
            with patch('toolchain.subprocess.check_output', return_value='compiler'), patch('toolchain.subprocess.run', return_value=result):
                with self.assertRaises(ValueError):
                    identify_compiler('/external/compiler', config)
