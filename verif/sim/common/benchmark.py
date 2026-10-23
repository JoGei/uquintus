"""Make helper for pinned benchmark builds and RTL execution; ports live in verif/sw/benchmark/."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

import yaml

from elf_image import load_elf
from hw_config import load_configuration
from pinned_archive import fetch, load_lock, verify_sources
from toolchain import compiler_command, discover_compiler, identify_compiler
from benchmark_measure import marker_addresses, software_compatible

ROOT = Path(__file__).resolve().parents[3]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def settings(name):
    if not re.fullmatch(r'[a-z][a-z0-9_-]*(?:/[a-z][a-z0-9_-]*)*', name):
        raise ValueError('benchmark must name a directory under verif/sw/benchmark/')
    port = ROOT / 'verif/sw/benchmark' / name
    if name == 'embench/embench-iot':
        from embench import settings as embench_settings
        return embench_settings(port, name)
    data = yaml.safe_load((port / 'config.yml').read_text())
    if (not isinstance(data, dict) or set(data) != {
            'schema_version', 'name', 'validator', 'sources', 'port_sources',
            'compiler_flags', 'defines', 'profiles', 'memory', 'max_cycles'} or
            data['schema_version'] != 1 or data['name'] != name or data['validator'] != 'coremark'):
        raise ValueError('invalid benchmark configuration/schema/validator')
    for field in ('sources', 'port_sources'):
        if not isinstance(data[field], list) or not data[field] or any(
                not isinstance(p, str) or not re.fullmatch(r'[a-zA-Z0-9_]+\.c', p) for p in data[field]):
            raise ValueError('benchmark sources must name C files in their source/port directory')
    if not isinstance(data['compiler_flags'], list) or any(
            not isinstance(p, str) or not p.startswith('-') for p in data['compiler_flags']):
        raise ValueError('compiler_flags must be a list of compiler options')
    if (not isinstance(data['defines'], dict) or set(data['defines']) != {'ITERATIONS', 'TOTAL_DATA_SIZE'} or
            type(data['defines']['ITERATIONS']) is not int or not 1 <= data['defines']['ITERATIONS'] <= 0x7fffffff or
            data['defines']['TOTAL_DATA_SIZE'] != 2000 or
            data['profiles'] != {'performance': {'PERFORMANCE_RUN': 1}, 'validation': {'VALIDATION_RUN': 1}}):
        raise ValueError('CoreMark needs positive fixed ITERATIONS, 2000 bytes and the two standard profiles')
    if (not isinstance(data['memory'], dict) or set(data['memory']) != {'imem_latency', 'dmem_latency'} or
            any(type(v) is not int or not 1 <= v <= 1000000 for v in data['memory'].values())):
        raise ValueError('memory latencies must be positive integer cycles')
    if type(data['max_cycles']) is not int or not 0 < data['max_cycles'] < 2**32:
        raise ValueError('benchmark max_cycles must fit the cycle-only 32-bit timer')
    lock = load_lock(port / 'lock.json')
    if lock['name'] != name:
        raise ValueError('benchmark lock name differs from configuration')
    return port, data, lock


def selected_profiles(data, profile):
    selected = list(data['profiles']) if profile == 'all' else profile.split(',')
    if not selected or len(set(selected)) != len(selected) or any(p not in data['profiles'] for p in selected):
        raise ValueError('unknown/duplicate benchmark profile; choose all or comma-separated names from: ' +
                         ', '.join(data['profiles']))
    return selected


def hardware(name):
    path = Path(name)
    if not path.is_file():
        path = ROOT / 'config' / (name + '.yml')
    path = path.resolve()
    config = load_configuration(path, json.loads((ROOT / 'config/selectors.json').read_text()))
    if any(config[k] for k in ('ISA_F', 'ISA_A', 'XIF', 'DEBUG', 'MUA_HARDENED')):
        raise ValueError('benchmark requires an implemented native ELF core profile')
    return path, config


def build(name, config_name, cc='', profile='all'):
    port, data, lock = settings(name)
    source = ROOT / 'build/deps' / (lock['name'] + '-' + lock['revision'])
    verify_sources(source, lock)  # Builds never fetch implicitly.
    embench = data['validator'] == 'embench'
    if embench:
        from embench import verify_manifest
        verify_manifest(source, data)
    profiles = selected_profiles(data, profile)
    config_path, config = hardware(config_name)
    compiler = identify_compiler(discover_compiler(cc), config)
    if compiler['family'] != 'gcc':
        raise ValueError('initial benchmark port requires GCC and its matching RV32 libgcc multilib')
    runtime = Path(subprocess.check_output(
        compiler_command(compiler) + ['-print-libgcc-file-name'], text=True).strip()).resolve()
    if not runtime.is_file():
        raise ValueError('compiler must supply a matching RV32 libgcc multilib')
    libraries = [runtime]
    if embench:
        libraries = []
        for library in data['libraries']:
            path = Path(subprocess.check_output(compiler_command(compiler) +
                ['-print-file-name=lib' + library + '.a'], text=True).strip()).resolve()
            if not path.is_file():
                raise ValueError('Embench requires matching RV32 lib' + library + '.a')
            libraries.append(path)
    parent = ROOT / 'build' / ('uquintus-' + config_path.stem) / 'sw/benchmark' / name
    directory = parent / ('build-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True)
    manifest = dict(schema_version=1, suite=name, status='running', parameters=config,
                    settings=data, upstream=lock, programs=[], selection=profile)
    inputs = [ROOT / 'verif/sw/common/crt0.S', ROOT / 'verif/sw/common/link.ld',
              *sorted(p for p in port.glob('*') if p.suffix in ('.c', '.h', '.yml', '.json')),
              *sorted(source.rglob('*.h')), *[source / p for p in data['sources']],
              *[source / p for selected in profiles for p in
                (data['profiles'][selected]['sources'] if embench else [])]]
    inputs = [p for p in inputs if p.is_file()]
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in inputs}
    for library in libraries:
        hashes[str(library)] = sha(library)
    try:
        for selected in profiles:
            output = directory / selected
            output.mkdir()
            workload = data['profiles'][selected]
            defines = dict(data['defines']) if embench else {**data['defines'], **workload}
            sources = list(data['sources'])
            if embench:
                sources += workload['sources']
                defines.update(UQU_EMBENCH_NAME='"' + selected + '"',
                               UQU_EMBENCH_SCALE=workload['local_scale_factor'])
            flags = [*data['compiler_flags'], '-mcmodel=medany', '-mno-relax', '-msmall-data-limit=0',
                     '-ffreestanding', '-fno-builtin', '-fno-pic', '-fno-stack-protector',
                     '-ffunction-sections', '-fdata-sections', '-nostdlib', '-static']
            command = compiler_command(compiler) + flags + [f'-D{k}={v}' for k, v in defines.items()]
            command += ['-I' + str(port), '-I' + str(source), '-I' + str(source / 'support'),
                        str(ROOT / 'verif/sw/common/crt0.S'),
                        *[str(source / p) for p in sources],
                        *[str(port / p) for p in data['port_sources']],
                        '-T', str(ROOT / 'verif/sw/common/link.ld'),
                        '-Wl,--gc-sections,--no-relax,-Map,program.map',
                        '-Wl,--start-group', *map(str, libraries), '-Wl,--end-group', '-o', 'program.elf']
            metadata = dict(configuration=str(config_path), parameters=config, compiler=compiler['version_string'],
                            compiler_info=compiler, upstream=lock, command=command, status='running',
                            source_sha256=hashes, runtime=dict(path=str(runtime), sha256=sha(runtime)),
                            benchmark=dict(name=name, validator=data['validator'], profile=selected,
                                iterations=1 if embench else defines['ITERATIONS'], memory=data['memory'], max_cycles=data['max_cycles'],
                                compiler_flags=flags, defines=defines, runtime_sha256=sha(runtime)))
            metadata['runtime_libraries'] = {str(p): sha(p) for p in libraries}
            if embench:
                metadata['benchmark'].update(arithmetic=workload['arithmetic'],
                    local_scale_factor=workload['local_scale_factor'], warmup_heat=defines['WARMUP_HEAT'],
                    workload_scale=defines['CPU_MHZ'],
                    verification='pinned upstream verify_benchmark must return exactly 1')
            try:
                result = subprocess.run(command, cwd=output, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                (output / 'build.log').write_text(result.stdout)
                if result.returncode:
                    raise RuntimeError(f'benchmark compilation failed; see {output / "build.log"}\n{result.stdout}')
                image = load_elf(output / 'program.elf')
                image.validate_core(config)
                image.tohost
                marker_addresses(image)
                metadata.update(status='passed', elf_sha256=sha(output / 'program.elf'))
                manifest['programs'].append(dict(profile=selected, path=str(output / 'program.elf'),
                                                 sha256=metadata['elf_sha256']))
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
        # A failed rebuild invalidates the latest selection rather than running
        # an older successful binary accidentally.
        (parent / 'suite.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Benchmark ELFs: {directory}; compiler {compiler["family"]} {compiler["version"]}')


def run(name, config_name, profile='all', sim='verilator', bender='bender', seed=1, waves=0, reference='none', spike='', elf=None, mode='fast', jobs=4, reuse_suite=None, retire_trace=False):
    from component_runner import main as run_component
    if mode not in ('fast', 'checked'):
        raise ValueError('benchmark mode must be fast or checked')
    if mode == 'fast' and (waves or reference != 'none'):
        raise ValueError('WAVES and REFERENCE require BENCHMARK_MODE=checked')
    if retire_trace and mode != 'fast':
        raise ValueError('BENCHMARK_TRACE requires BENCHMARK_MODE=fast; checked mode already retains RVFI')
    _, data, lock = settings(name)
    config_path, config = hardware(config_name)
    profiles = selected_profiles(data, profile)
    if elf and reuse_suite:
        raise ValueError('ELF and BENCHMARK_REUSE_SUITE are mutually exclusive')
    if elf:
        if profile == 'all':
            raise ValueError('ELF reuse requires one explicit BENCHMARK_PROFILE')
        elf = Path(elf).resolve()
        metadata = json.loads((elf.parent / 'build.json').read_text())
        b = metadata.get('benchmark', {})
        if (metadata.get('upstream') != lock or b.get('name') != name or b.get('profile') != profile or
                b.get('iterations') != (1 if data['validator'] == 'embench' else data['defines']['ITERATIONS'])):
            raise ValueError('reused ELF benchmark/profile/pin differs from requested workload')
        programs = [dict(profile=profile, path=str(elf), sha256=metadata['elf_sha256'])]
    else:
        path = (Path(reuse_suite).resolve() if reuse_suite else
                ROOT / 'build' / ('uquintus-' + config_path.stem) / 'sw/benchmark' / name / 'suite.json')
        suite = json.loads(path.read_text())
        compatible = (software_compatible(suite.get('parameters', {}), config) if reuse_suite
                      else suite.get('parameters') == config)
        if (suite.get('status') != 'passed' or not compatible or
                suite.get('settings') != data or suite.get('upstream') != lock or not suite.get('programs')):
            raise ValueError('benchmark build is missing, failed or stale; run make benchmark-build')
        programs = suite['programs']
    shared, failures = {}, []
    suite_directory = ROOT / 'build' / ('uquintus-' + config_path.stem) / sim / 'benchmark' / name / (
        'suite-' + mode + '-' + uuid.uuid4().hex[:12])
    suite_directory.mkdir(parents=True)
    execution = dict(schema_version=1, suite=name, status='running', execution_mode=mode,
        configuration=str(config_path), parameters=config, settings=data, upstream=lock,
        requested=profiles, upstream_workloads=list(data['profiles']), results=[],
        full_suite_selected=set(profiles) == set(data['profiles']),
        started_at=datetime.now(timezone.utc).isoformat())
    execution['diagnostic_retirement_trace'] = bool(retire_trace)
    if reuse_suite:
        execution['reused_software_suite'] = str(path)
        execution['software_parameters'] = suite['parameters']
    summary_path = suite_directory / 'suite-results.json'
    summary_path.write_text(json.dumps(execution, indent=2) + '\n')
    for selected in profiles:
        program = next((p for p in programs if p['profile'] == selected), None)
        try:
            if program is None or sha(Path(program['path'])) != program['sha256']:
                raise ValueError('benchmark ELF missing/changed; rebuild')
            if mode == 'fast':
                from benchmark_fast import run_fast
                directory = run_fast(program['path'], config_path, config, bender=bender, simulator=sim,
                                     seed=seed, shared_build=shared, jobs=jobs, retire_trace=retire_trace)
            else:
                directory = run_component(['--component', 'core_elf', '--config', str(config_path), '--test', 'execute',
                           '--elf', program['path'], '--label', name + '-' + selected, '--benchmark',
                           '--max-cycles', str(data['max_cycles']), '--seed', str(seed),
                           '--imem-latency', str(data['memory']['imem_latency']),
                           '--dmem-latency', str(data['memory']['dmem_latency']),
                           '--sim', sim, '--bender', bender, '--waves', str(waves),
                           '--reference', reference, '--spike', spike], shared_build=shared)
            execution['results'].append(dict(profile=selected, status='passed', directory=str(directory),
                                              elf_sha256=program['sha256']))
        except Exception as error:
            failures.append(selected)
            execution['results'].append(dict(profile=selected, status='failed', detail=str(error),
                                              directory=str(getattr(error, 'run_dir', ''))))
            print(f'{selected}: {error}', file=sys.stderr)
        finally:
            summary_path.write_text(json.dumps(execution, indent=2) + '\n')
    execution.update(status='failed' if failures else 'passed',
                     finished_at=datetime.now(timezone.utc).isoformat())
    summary_path.write_text(json.dumps(execution, indent=2) + '\n')
    print('Suite execution:', summary_path)
    if failures:
        raise RuntimeError('benchmark failed: ' + ', '.join(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('fetch', 'build', 'run'))
    parser.add_argument('--benchmark', default='coremark')
    parser.add_argument('--profile', default='all', help='all or comma-separated suite workload names')
    parser.add_argument('--config', default='rv32i')
    parser.add_argument('--cc', default='')
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--sim', default='verilator')
    parser.add_argument('--bender', default='bender')
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--waves', type=int, choices=(0, 1), default=0)
    parser.add_argument('--reference', choices=('none', 'spike'), default='none')
    parser.add_argument('--spike', default='')
    parser.add_argument('--mode', choices=('fast', 'checked'), default='fast')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--elf', type=Path, help='reuse one built benchmark ELF across compatible MUA configurations')
    parser.add_argument('--reuse-suite', type=Path, help='reuse a built suite.json across compatible MUA configurations')
    parser.add_argument('--retire-trace', type=int, choices=(0, 1), default=0,
                        help='retain a diagnostic retirement trace in fast mode')
    args = parser.parse_args()
    if args.action == 'fetch':
        _, _, lock = settings(args.benchmark)
        print('Pinned sources:', fetch(ROOT / 'build/deps', lock, args.archive))
    elif args.action == 'build':
        build(args.benchmark, args.config, args.cc, args.profile)
    else:
        run(args.benchmark, args.config, args.profile, args.sim, args.bender,
            args.seed, args.waves, args.reference, args.spike, args.elf, args.mode, args.jobs, args.reuse_suite,
            bool(args.retire_trace))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError, KeyError, subprocess.CalledProcessError, yaml.YAMLError) as error:
        sys.exit(str(error))
