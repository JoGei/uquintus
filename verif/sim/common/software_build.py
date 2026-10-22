"""GNU Make helper: build a small bare-metal test with an external GCC/Clang."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import yaml

from elf_image import expected_traps, load_elf
from hw_config import load_configuration
from toolchain import compiler_command, discover_compiler, identify_compiler
from interrupts import interrupt_plan

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='rv32i')
    parser.add_argument('--program', default='smoke')
    parser.add_argument('--cc', default='')
    args = parser.parse_args()
    if not re.fullmatch('[a-z][a-z0-9_]*', args.program):
        raise ValueError('program must name a directory under verif/sw/')
    candidates = [ROOT / 'verif/sw' / args.program / ('main'+suffix) for suffix in ('.c', '.S')]
    sources = [p for p in candidates if p.is_file()]
    if len(sources) != 1:
        raise ValueError(f'program needs exactly one main.c or main.S: {candidates[0].parent}')
    source = sources[0]
    config_path = Path(args.config)
    if not config_path.is_file():
        config_path = ROOT / 'config' / f'{args.config}.yml'
    catalog = json.loads((ROOT / 'config/selectors.json').read_text())
    config = load_configuration(config_path, catalog)
    if any(config[name] for name in ('ISA_F', 'ISA_ZFINX', 'ISA_A', 'XIF', 'DEBUG', 'MUA_HARDENED')):
        raise ValueError('software smoke build requires the implemented native core profile')
    compiler = identify_compiler(discover_compiler(args.cc), config)
    directory = ROOT / 'build' / f'uquintus-{config_path.stem}' / 'sw' / args.program
    directory.mkdir(parents=True, exist_ok=True)
    common = ROOT / 'verif/sw/common'
    inputs = [common / 'crt0.S', source, common / 'link.ld']
    command = compiler_command(compiler)
    command += [f'-DUQU_ISA_UMODE={config["ISA_UMODE"]}', '-mcmodel=medany', '-mno-relax',
                '-msmall-data-limit=0', '-ffreestanding', '-fno-builtin', '-fno-pic',
                '-fno-stack-protector', '-ffunction-sections', '-fdata-sections',
                '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-nostdlib',
                str(inputs[0]), str(inputs[1]), '-T', str(inputs[2]),
                '-Wl,--gc-sections,--no-relax,-Map,program.map', '-o', 'program.elf']
    metadata = {
        'configuration': str(config_path.resolve()), 'parameters': config,
        'compiler': compiler['version_string'], 'compiler_info': compiler,
        'command': command, 'status': 'running',
        'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in inputs},
    }
    try:
        result = subprocess.run(command, cwd=directory, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (directory / 'build.log').write_text(result.stdout)
        if result.returncode:
            raise RuntimeError(f'software build failed; see {directory / "build.log"}\n{result.stdout}')
        image = load_elf(directory / 'program.elf')
        image.validate_core(config)
        image.tohost
        metadata.update(status='passed', expected_traps=expected_traps(image), interrupt_plan=interrupt_plan(image,config), elf_sha256=hashlib.sha256(
            (directory / 'program.elf').read_bytes()).hexdigest())
    except BaseException:
        metadata['status'] = 'failed'
        raise
    finally:
        (directory / 'build.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(f'ELF: {directory / "program.elf"}')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError, yaml.YAMLError) as error:
        sys.exit(str(error))
