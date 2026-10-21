"""Discover and identify an externally supplied RISC-V compiler, without installs."""
import os
from pathlib import Path
import re
import shutil
import subprocess


def isa_abi(config):
    march = 'rv32' + ('e' if config['ISA_E'] else 'i')
    march += ('m' if config['ISA_M'] else '') + ('c' if config['ISA_C'] else '') + '_zicsr'
    march += '_zifencei' if config['ISA_ZIFENCEI'] else ''
    return march, 'ilp32e' if config['ISA_E'] else 'ilp32'


def discover_compiler(explicit=None, environ=None):
    environment = os.environ if environ is None else environ
    selected = explicit or environment.get('RISCV_CC')
    if selected:
        candidates = [selected]
    else:
        names = ['riscv32-unknown-elf-gcc', 'riscv64-unknown-elf-gcc', 'clang']
        candidates = []
        if environment.get('RISCV'):
            directory = Path(environment['RISCV']) / 'bin'
            candidates += [str(directory / name) for name in names]
        candidates += names
    for candidate in candidates:
        executable = shutil.which(candidate, path=environment.get('PATH', os.defpath))
        if executable:
            # Preserve the invoked name: GCC/Clang drivers may use it to locate
            # toolchain resources even when the executable is a symlink.
            return str(Path(executable).absolute())
    raise ValueError('RISC-V compiler not found; set RISCV_CC, provide $RISCV/bin, '
                     'or put riscv32/64-unknown-elf-gcc or Clang/LLD on PATH')


def identify_compiler(executable, config):
    march, abi = isa_abi(config)
    banner = subprocess.check_output([executable, '--version'], text=True, stderr=subprocess.STDOUT).strip()
    # Host Clang is also a cross compiler when its RISC-V backend is enabled.
    options = ['--target=riscv32-unknown-elf'] if 'clang' in banner.lower() else []
    options += [f'-march={march}', f'-mabi={abi}']
    probe = subprocess.run([executable, *options, '-dM', '-E', '-x', 'c', '-'],
                           input='', text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if probe.returncode:
        raise ValueError(f'compiler cannot target {march}/{abi}: {probe.stderr.strip()}')
    macros = dict(re.findall(r'^#define\s+(\w+)\s+(.*)$', probe.stdout, re.M))
    if macros.get('__riscv_xlen') != '32':
        raise ValueError('compiler probe did not report a 32-bit RISC-V target')
    if '__clang__' in macros:
        family = 'clang'
        version = '.'.join(macros[name] for name in ('__clang_major__', '__clang_minor__', '__clang_patchlevel__'))
    elif '__GNUC__' in macros:
        family = 'gcc'
        version = '.'.join(macros[name] for name in ('__GNUC__', '__GNUC_MINOR__', '__GNUC_PATCHLEVEL__'))
    else:
        raise ValueError('unsupported compiler type: expected GCC or Clang')
    target = subprocess.check_output([executable, *options, '-dumpmachine'], text=True).strip()
    return {'executable': executable, 'resolved_executable': str(Path(executable).resolve()),
            'family': family, 'version': version, 'version_string': banner,
            'target': target, 'march': march, 'abi': abi, 'target_options': options}


def compiler_command(info):
    return [info['executable'], *info['target_options'], *(
        ['-fuse-ld=lld'] if info['family'] == 'clang' else [])]
