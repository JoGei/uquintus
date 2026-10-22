"""Fetch a checksum-pinned source archive and build bare-metal riscv-tests ELFs."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.request import urlopen

import yaml

from elf_image import load_elf
from hw_config import load_configuration
from toolchain import compiler_command, discover_compiler, identify_compiler

ROOT = Path(__file__).resolve().parents[3]
INTEGRATION = ROOT / 'verif/sw/riscv_tests'


def load_lock():
    lock = json.loads((INTEGRATION / 'lock.json').read_text())
    if (lock.get('schema_version') != 1 or
            not re.fullmatch('[0-9a-f]{40}', lock.get('revision', '')) or
            not re.fullmatch('[0-9a-f]{64}', lock.get('archive_sha256', ''))):
        raise ValueError('invalid riscv-tests lock')
    return lock


def extract_archive(archive, destination, lock):
    if hashlib.sha256(archive.read_bytes()).hexdigest() != lock['archive_sha256']:
        raise ValueError('riscv-tests archive SHA-256 does not match lock.json')
    expected = 'riscv-tests-' + lock['revision']
    with tarfile.open(archive, 'r:gz') as source:
        members = []
        for member in source.getmembers():
            parts = Path(member.name).parts
            if not parts or parts[0] != expected or '..' in parts:
                raise ValueError('unexpected path/link in riscv-tests archive')
            # The unrelated debug tree contains a symlink into the upstream
            # env submodule. Only ISA sources and their license are consumed.
            if len(parts) > 1 and parts[1] not in ('isa', 'LICENSE', 'README.md'):
                continue
            if not (member.isdir() or member.isfile()):
                raise ValueError('unexpected link in riscv-tests ISA sources')
            members.append(member)
        source.extractall(destination, members=members, filter='data')
    return destination / expected


def fetch(archive_path=None):
    lock = load_lock()
    cache = ROOT / 'build/deps'
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / ('riscv-tests-' + lock['revision'])
    if destination.exists():
        verify_sources(destination, lock)
        print(f'Pinned sources: {destination}')
        return destination
    with tempfile.TemporaryDirectory(prefix='.riscv-tests-', dir=cache) as temporary:
        directory = Path(temporary)
        archive = directory / 'source.tar.gz'
        if archive_path:
            shutil.copyfile(archive_path, archive)
        else:
            with urlopen(lock['archive_url'], timeout=60) as response, archive.open('wb') as output:
                shutil.copyfileobj(response, output)
        extracted = extract_archive(archive, directory, lock)
        inventory = {p.relative_to(extracted).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in extracted.rglob('*') if p.is_file()}
        (extracted / '.uqu-source.json').write_text(json.dumps({
            'revision': lock['revision'], 'archive_sha256': lock['archive_sha256'],
            'files': inventory}, indent=2) + '\n')
        extracted.rename(destination)
    print(f'Pinned sources: {destination}')
    return destination


def verify_sources(directory, lock):
    inventory_path = directory / '.uqu-source.json'
    if not inventory_path.is_file():
        raise ValueError('pinned source cache missing; run make riscv-tests-fetch')
    inventory = json.loads(inventory_path.read_text())
    if (inventory.get('revision') != lock['revision'] or
            inventory.get('archive_sha256') != lock['archive_sha256']):
        raise ValueError('riscv-tests cache pin does not match lock.json')
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob('*')
              if p.is_file() and p != inventory_path}
    if actual != set(inventory['files']):
        raise ValueError('riscv-tests source cache file set changed; refetch the pinned archive')
    for name, expected in inventory['files'].items():
        path = directory / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'riscv-tests cached source changed: {name}; refetch the pinned archive')


def upstream_names(directory, group):
    text = (directory / 'isa' / group / 'Makefrag').read_text()
    match = re.search(r'^' + group + r'_sc_tests\s*=\s*(.*?)(?=^\w+\s*=|\Z)', text, re.M | re.S)
    if not match:
        raise ValueError(f'cannot parse pinned {group} test list')
    names = match[1].replace('\\\n', ' ').split()
    if not names or any(not re.fullmatch('[a-z0-9_]+', name) for name in names):
        raise ValueError(f'invalid pinned {group} test names')
    return names


def select_tests(directory, config, selection='all'):
    if config['ISA_E']:
        raise ValueError('upstream rv32ui uses x16-x31; RV32E riscv-tests integration is unsupported')
    tests, excluded = [], []
    for group in ('rv32ui', 'rv32um', 'rv32uc'):
        for name in upstream_names(directory, group):
            case = group + '-p-' + name
            reason = ('test requires successful misaligned accesses; core traps instead' if name == 'ma_data' else
                      'ISA_ZIFENCEI=0' if name == 'fence_i' and not config['ISA_ZIFENCEI'] else
                      'ISA_M=0' if group == 'rv32um' and not config['ISA_M'] else
                      'ISA_C=0' if group == 'rv32uc' and not config['ISA_C'] else None)
            if reason:
                excluded.append({'name': case, 'reason': reason})
            else:
                tests.append({'name': case, 'source': f'isa/{group}/{name}.S'})
    if selection != 'all':
        requested = selection.split(',')
        available = {test['name']: test for test in tests}
        for name in requested:
            if name not in available:
                reason = next((e['reason'] for e in excluded if e['name'] == name), 'unknown test name')
                raise ValueError(f'cannot select {name}: {reason}')
        tests = [available[name] for name in dict.fromkeys(requested)]
    return tests, excluded


def build(config_name, cc='', selection='all'):
    lock = load_lock()
    source_dir = ROOT / 'build/deps' / ('riscv-tests-' + lock['revision'])
    verify_sources(source_dir, lock)  # Builds never fetch implicitly.
    config_path = Path(config_name)
    if not config_path.is_file():
        config_path = ROOT / 'config' / f'{config_name}.yml'
    config_path = config_path.resolve()
    config = load_configuration(config_path, json.loads((ROOT / 'config/selectors.json').read_text()))
    if any(config[name] for name in ('ISA_F', 'ISA_ZFINX', 'ISA_A', 'XIF', 'DEBUG', 'MUA_HARDENED')):
        raise ValueError('riscv-tests build requires an implemented native core configuration')
    tests, excluded = select_tests(source_dir, config, selection)
    compiler = identify_compiler(discover_compiler(cc), config)
    directory = ROOT / 'build' / f'uquintus-{config_path.stem}' / 'sw/riscv-tests'
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {'schema_version': 1, 'suite': 'riscv-tests', 'upstream': lock,
                'configuration': str(config_path), 'parameters': config,
                'compiler_info': compiler, 'programs': [], 'excluded': excluded,
                'selection': selection, 'status': 'running'}
    try:
        for test in tests:
            output = directory / test['name']
            output.mkdir(exist_ok=True)
            command = compiler_command(compiler) + [
                '-mcmodel=medany', '-mno-relax', '-nostdlib', '-static', '-fno-pic',
                '-I' + str(INTEGRATION), '-I' + str(source_dir / 'isa/macros/scalar'),
                str(ROOT / 'verif/sw/common/crt0.S'), str(source_dir / test['source']),
                '-T', str(ROOT / 'verif/sw/common/link.ld'),
                '-Wl,--no-relax,-Map,program.map', '-o', 'program.elf']
            metadata = {'configuration': str(config_path), 'parameters': config,
                        'compiler': compiler['version_string'], 'compiler_info': compiler,
                        'upstream': lock, 'test_name': test['name'], 'command': command,
                        'status': 'running', 'source_sha256': {}}
            inputs = [ROOT / 'verif/sw/common/crt0.S', ROOT / 'verif/sw/common/link.ld',
                      INTEGRATION / 'riscv_test.h', INTEGRATION / 'lock.json']
            inputs += [p for p in (source_dir / 'isa').rglob('*') if p.is_file() and
                       p.suffix in ('.S', '.h') and ('macros/scalar' in str(p) or
                       p.parent.name in ('rv32ui', 'rv64ui', 'rv32um', 'rv64um', 'rv32uc', 'rv64uc'))]
            metadata['source_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
            try:
                result = subprocess.run(command, cwd=output, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                (output / 'build.log').write_text(result.stdout)
                if result.returncode:
                    raise RuntimeError(f'{test["name"]} build failed; see {output / "build.log"}\n{result.stdout}')
                image = load_elf(output / 'program.elf')
                image.validate_core(config)
                image.tohost
                sha = hashlib.sha256((output / 'program.elf').read_bytes()).hexdigest()
                metadata.update(status='passed', elf_sha256=sha)
                manifest['programs'].append({'name': test['name'], 'path': str(output / 'program.elf'),
                                             'sha256': sha, 'build_metadata': str(output / 'build.json')})
            except BaseException:
                metadata['status'] = 'failed'
                raise
            finally:
                (output / 'build.json').write_text(json.dumps(metadata, indent=2) + '\n')
        manifest['status'] = 'passed'
    except BaseException:
        manifest['status'] = 'failed'
        raise
    finally:
        (directory / 'suite.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'{len(tests)} ELFs built; {len(excluded)} explicitly excluded')
    print(f'Compiler: {compiler["family"]} {compiler["version"]}, target {compiler["target"]}')
    print(f'Suite: {directory / "suite.json"}')
    return directory / 'suite.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('fetch', 'build', 'run'))
    parser.add_argument('--archive', type=Path, help='offline copy of the checksum-pinned archive')
    parser.add_argument('--config', default='rv32i')
    parser.add_argument('--cc', default='')
    parser.add_argument('--tests', default='all', help='all or comma-separated full upstream test names')
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--sim', default='verilator')
    parser.add_argument('--bender', default='bender')
    parser.add_argument('--max-cycles', type=int, default=100000)
    parser.add_argument('--waves', type=int, choices=(0, 1), default=0)
    parser.add_argument('--reference', choices=('none', 'spike'), default='none')
    parser.add_argument('--spike', default='')
    args = parser.parse_args()
    if args.action == 'fetch':
        fetch(args.archive)
    elif args.action == 'build':
        build(args.config, args.cc, args.tests)
    else:
        from elf_suite import run_suite
        config_path = Path(args.config)
        if not config_path.is_file():
            config_path = ROOT / 'config' / f'{args.config}.yml'
        config_path = config_path.resolve()
        config = load_configuration(config_path, json.loads((ROOT / 'config/selectors.json').read_text()))
        manifest = ROOT / 'build' / f'uquintus-{config_path.stem}/sw/riscv-tests/suite.json'
        suite = json.loads(manifest.read_text())
        if suite.get('upstream') != load_lock():
            raise ValueError('built suite pin differs from lock.json; rebuild')
        run_suite(manifest, config_path, config, root=ROOT, seed=args.seed,
                  simulator=args.sim, bender=args.bender, max_cycles=args.max_cycles, waves=args.waves,
                  reference=args.reference, spike=args.spike)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError, yaml.YAMLError) as error:
        sys.exit(str(error))
