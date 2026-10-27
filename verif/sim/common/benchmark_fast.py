"""Build a native Verilator driver; no Python, VPI or trace callbacks during execution."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET

import yaml

from benchmark_measure import BenchmarkWindow, benchmark_result, marker_addresses, read_log, software_compatible
from component_runner import (HDL_LANGUAGE_ARGS, bender_include_dirs, bender_source_options,
                              command_output, load_component, order_control_files, simulator_build_key)
from elf_image import load_elf, expected_traps
from hw_config import parameters_for_component, write_header
from bpu_stats import SCOPE as BPU_SCOPE, statistics as bpu_statistics, metrics as bpu_metrics
from interrupts import interrupt_plan

ROOT = Path(__file__).resolve().parents[3]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_memory(image, path):
    with path.open('wb') as stream:
        stream.write(b'UQUMEM01' + struct.pack('<I', len(image.segments)))
        for segment in image.segments:
            stream.write(struct.pack('<III', segment.address, len(segment.data), segment.size))
            stream.write(segment.data)


def read_memory(path):
    raw = path.read_bytes()
    if len(raw) < 12 or raw[:8] != b'UQUMEM01':
        raise ValueError('invalid final memory image')
    count, = struct.unpack_from('<I', raw, 8)
    offset, memory = 12, {}
    if count > 4096 or len(raw) > 17*1024*1024:
        raise ValueError('final memory image exceeds limits')
    for _ in range(count):
        if offset + 12 > len(raw):
            raise ValueError('truncated final memory segment')
        address, filesz, memsz = struct.unpack_from('<III', raw, offset)
        offset += 12
        if filesz > memsz or offset+filesz > len(raw) or address+memsz > 2**32 or len(memory)+memsz > 16*1024*1024:
            raise ValueError('invalid final memory segment size')
        for n in range(memsz):
            if address+n in memory:
                raise ValueError('overlapping final memory segments')
            memory[address+n] = raw[offset+n] if n < filesz else 0
        offset += filesz
    if offset != len(raw):
        raise ValueError('trailing final memory data')
    return memory


def run_fast(program, config_path, config, *, bender='bender', simulator='verilator', seed=1, shared_build=None, jobs=4, retire_trace=False, power_activity=None):
    program = Path(program).resolve()
    image = load_elf(program)
    image.validate_core(config)
    image.tohost
    start_pc, stop_pc = marker_addresses(image)
    if expected_traps(image) or interrupt_plan(image, config):
        raise ValueError('fast benchmarking does not run declared exception/interrupt scenarios')
    software = json.loads((program.parent / 'build.json').read_text())
    benchmark = software.get('benchmark')
    if (software.get('status') != 'passed' or software.get('elf_sha256') != sha(program) or
            not software_compatible(software.get('parameters', {}), config) or not isinstance(benchmark, dict)):
        raise ValueError('fast benchmark requires successful matching ELF build metadata')
    for name, expected in software['source_sha256'].items():
        source = ROOT / name
        if not source.is_file() or sha(source) != expected:
            raise ValueError(f'benchmark build input changed: {name}; rebuild')
    if simulator != 'verilator' or jobs < 1:
        raise ValueError('fast benchmark requires Verilator and positive JOBS')
    for tool in (simulator, bender):
        if not shutil.which(tool):
            raise ValueError(f'required tool not found: {tool}')
    directory = ROOT / 'build' / ('uquintus-' + config_path.stem) / simulator / 'benchmark' / benchmark['name'] / (
        'fast-' + benchmark['profile'] + '-seed' + str(seed) + '-' + uuid.uuid4().hex[:12])
    directory.mkdir(parents=True)
    catalog = json.loads((ROOT / 'config/selectors.json').read_text())
    write_header(catalog, directory / 'include')
    (directory / 'config.yml').write_text(yaml.safe_dump(config, sort_keys=False))
    (directory / 'software-build.json').write_text(json.dumps(software, indent=2)+'\n')
    shutil.copyfile(program, directory / 'program.elf')
    write_memory(image, directory / 'program-image.bin')
    # The RTL target excludes all cocotb/RVFI/trace wrappers. Retain Bender's
    # existing optional imported-IP selection for enabled Zfinx configurations.
    component = dict(load_component('core_elf'), bender_target='rtl')
    component['bender_targets'] = [*component.get('bender_targets', []), 'benchmark_stats']
    parameters = parameters_for_component(config, component['parameters'], catalog)
    options = bender_source_options(component, simulator, parameters)
    source_text = command_output([bender, 'script', 'flist', *options])
    sources = [(ROOT / p.strip()).resolve() for p in source_text.splitlines() if p.strip() and not p.lstrip().startswith('//')]
    wrapper = ROOT / 'verif/sim/benchmark/uqu_benchmark_tb.sv'
    driver = ROOT / 'verif/sim/benchmark/main.cpp'
    sources = order_control_files([*sources, wrapper])
    tree = command_output([bender, 'sources', *options])
    includes = [directory / 'include', *bender_include_dirs(json.loads(tree))]
    activity_args = []
    if power_activity is not None:
        # The power flow supplies the exact placed netlist and Liberty-derived
        # functional cells. The unmodified RTL remains the benchmark oracle.
        sources += [Path(p) for p in power_activity['sources']]
        includes.append(Path(power_activity['include']))
        activity_args = ['--trace', '--trace-underscore', '--trace-depth', '3',
                         '--timescale-override', '1ns/1ps', '-DUQU_POWER_ACTIVITY',
                         str(power_activity['trace_config']), '-LDFLAGS', '-lz',
                         '-MAKEFLAGS', 'OPT_FAST=-O3 OPT_SLOW=-O0']
    headers = sorted({p for d in includes for pattern in ('*.vh', '*.svh') for p in d.rglob(pattern)})
    if power_activity is not None:
        headers.append(ROOT / 'verif/sim/benchmark/activity_vcd.h')
    (directory / 'sources.f').write_text(''.join(str(p)+'\n' for p in sources))
    (directory / 'bender_sources.json').write_text(tree+'\n')
    compiler = command_output([*shlex.split(os.environ.get('CXX', 'g++')), '--version'])
    simulator_info = command_output([simulator, '--version'])
    key_sources = [*sources, driver]
    if power_activity is not None:
        key_sources.append(Path(power_activity['trace_config']))
    key = simulator_build_key(key_sources, headers, includes, parameters,
        'uqu_benchmark_tb', simulator_info + compiler + str(activity_args), bool(power_activity), directory / 'include')
    inputs = dict(software['source_sha256'])
    for source in [*sources, *headers, driver, ROOT / 'Bender.yml', ROOT / 'config/selectors.json',
                   ROOT / 'config/sim/core_elf.yml', Path(__file__), ROOT / 'verif/sim/common/benchmark_measure.py',
                   ROOT / 'verif/sim/common/elf_image.py']:
        inputs[str(source.relative_to(ROOT)) if source.is_relative_to(ROOT) else str(source)] = sha(source)
    inputs['verif/sim/common/bpu_stats.py'] = sha(ROOT / 'verif/sim/common/bpu_stats.py')
    if power_activity is not None:
        for source in (ROOT / 'verif/sim/benchmark/activity_vcd.h', Path(power_activity['trace_config'])):
            inputs[str(source)] = sha(source)
    if retire_trace:
        inputs['verif/sim/common/benchmark_prediction.py'] = sha(ROOT / 'verif/sim/common/benchmark_prediction.py')
    if config['ISA_ZFINX']:
        inputs['Bender.lock'] = sha(ROOT / 'Bender.lock')
        shutil.copyfile(ROOT / 'Bender.lock', directory / 'Bender.lock')
    context = dict(benchmark=benchmark, memory=dict(benchmark['memory'], grants='immediate',
        fence_ack='immediate', ports='independent', response_errors='none'), execution_mode='fast',
        validation_scope=('workload_crc_completion_traps_watchdog_and_timer_window' if benchmark['validator'] == 'coremark'
                          else 'upstream_self_check_completion_traps_watchdog_and_timer_window'),
        family=software['compiler_info']['family'], version=software['compiler_info']['version'],
        march=software['compiler_info']['march'], abi=software['compiler_info']['abi'],
        suite_revision=software['upstream']['revision'],
        measurement='retirement edges (start, stop]; timer call overhead included', bpu_statistics=BPU_SCOPE)
    record = dict(schema_version=1, kind='benchmark', status='running', configuration_scope='core',
        component='core_elf', target=simulator, selection=benchmark['name']+'-'+benchmark['profile'], seed=seed,
        configuration=dict(name=config_path.stem, parameters=config), context=context,
        compiler=software['compiler'], compiler_info=software['compiler_info'], upstream=software['upstream'],
        simulator=simulator_info, host_compiler=compiler, bender=command_output([bender, '--version']),
        source_sha256=inputs, input_scope='RTL, headers, software/runtime, native harness and measurement adapter',
        workload=sha(program), metrics=[], results_file='results.xml', required_tests=[
            'workload_crc' if benchmark['validator'] == 'coremark' else 'workload_self_check'],
        started_at=datetime.now(timezone.utc).isoformat(),
        artifacts=['benchmark.json', 'benchmark.log', 'bpu-stats.json', 'native.json', 'native.log', 'execution.json',
                   'build.log', 'sources.f', 'bender_sources.json', 'software-build.json', 'config.yml',
                   'program-image.bin', 'final-memory.bin'])
    report_path = directory / 'report.json'
    if retire_trace:
        record['diagnostic_retirement_trace'] = dict(file='retire.bin', format='UQUTRC01',
            record='little-endian uint32 cycle, pc, original instruction bytes', scope='whole execution including startup/warmup')
        record['artifacts'].append('retire.bin')
    report_path.write_text(json.dumps(record, indent=2)+'\n')
    xml = ET.Element('testsuites')
    case = ET.SubElement(ET.SubElement(xml, 'testsuite', name='benchmark-fast'), 'testcase', name=record['required_tests'][0])
    evidence = dict(schema_version=1, status='failed', mode='fast')
    print('Artifacts:', directory, flush=True)
    started = time.monotonic()
    try:
        if shared_build is not None and shared_build.get('key') == key:
            executable = shared_build['executable']
            record['reused_simulator_build'] = str(executable.parent)
            compile_seconds = 0.0
        else:
            build_dir = directory / 'obj'
            command = [simulator, '--cc', '--exe', '--build', '--assert', '-j', str(jobs),
                '--top-module', 'uqu_benchmark_tb', '--prefix', 'Vuqu_benchmark_tb',
                '-Mdir', str(build_dir), '-o', 'uqu_benchmark', '-O3', '-CFLAGS',
                ('-std=c++17 -DUQU_POWER_ACTIVITY' if power_activity is not None else '-O3 -std=c++17'),
                *HDL_LANGUAGE_ARGS, *activity_args, *['-I'+str(p) for p in includes],
                *[f'-G{k}={v}' for k, v in parameters.items()], *[str(p) for p in sources], str(driver)]
            record['build_command'] = command
            before = time.monotonic()
            result = subprocess.run(command, cwd=directory, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            compile_seconds = time.monotonic()-before
            (directory / 'build.log').write_text(result.stdout)
            if result.returncode:
                raise RuntimeError('native Verilator build failed; see build.log\n'+result.stdout[-4000:])
            executable = build_dir / 'uqu_benchmark'
            if shared_build is not None:
                shared_build.update(key=key, executable=executable)
        record['executable_sha256'] = sha(executable)
        memory = benchmark['memory']
        command = [str(executable), 'program-image.bin', str(benchmark['max_cycles']), str(image.entry),
            str(memory['imem_latency']), str(memory['dmem_latency']), str(image.tohost), str(start_pc), str(stop_pc)]
        if retire_trace:
            command.append('retire.bin')
        record['command'] = command
        before = time.monotonic()
        environment = dict(os.environ)
        if power_activity is not None:
            environment['UQU_POWER_PERIOD_PS'] = str(power_activity['period_ps'])
            record['context']['activity'] = dict(scope='TOP/uqu_benchmark_tb/u_gate',
                window='post start retirement edge to post stop retirement edge',
                clock_period_ps=power_activity['period_ps'], netlist='repaired zero-delay functional cells')
            record['artifacts'].append('activity.vcd.gz')
        result = subprocess.run(command, cwd=directory, env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        elapsed = time.monotonic()-before
        record.update(compile_wall_seconds=compile_seconds, simulation_wall_seconds=elapsed)
        (directory / 'native.log').write_text(result.stdout)
        native_path = directory / 'native.json'
        native = json.loads(native_path.read_text()) if native_path.is_file() else {}
        (directory / 'execution.json').write_text(json.dumps(native, indent=2)+'\n')
        if result.returncode or native.get('status') != 'passed':
            raise RuntimeError(native.get('detail') or 'native simulation failed; see native.log')
        if retire_trace:
            from benchmark_prediction import validate_trace
            record['diagnostic_retirement_trace'].update(validate_trace(directory / 'retire.bin', native))
        window = BenchmarkWindow(image)
        window.start, window.stop = native['start'], native['stop']
        measured = window.finish()
        bpu = bpu_statistics(native['bpu_start'], native['bpu_stop'], config, measured['retired'])
        (directory / 'bpu-stats.json').write_text(json.dumps(bpu, indent=2)+'\n')
        log = read_log(image, read_memory(directory / 'final-memory.bin'))
        (directory / 'benchmark.log').write_text(log)
        validated = benchmark_result(log, benchmark, measured['cycles'])
        evidence.update(status='passed', window=measured, result=validated, memory=memory,
                        validation_scope=context['validation_scope'], bpu_statistics=bpu)
        record['metrics'] = [dict(name=name, value=value, unit=unit) for name, value, unit in (
            ('benchmark_cycles', measured['cycles'], 'cycles'), ('benchmark_retired', measured['retired'], 'instructions'),
            ('benchmark_cpi', measured['cpi'], 'cycles/instruction'),
            ('cycles_per_iteration', validated['cycles_per_iteration'], 'cycles/iteration'),
            ('elf_load_bytes', sum(s.size for s in image.segments), 'bytes'),
            ('executable_segment_bytes', sum(len(s.data) for s in image.segments if s.flags & 1), 'bytes'))]
        record['metrics'] += bpu_metrics(bpu)
        record['status'] = 'passed'
    except BaseException as error:
        record.update(status='failed', detail=str(error))
        evidence.update(status='failed', detail=str(error))
        error.run_dir = directory
        ET.SubElement(case, 'failure', message=str(error)).text = str(error)
        raise
    finally:
        case.set('time', str(time.monotonic()-started))
        ET.ElementTree(xml).write(directory / 'results.xml', encoding='unicode', xml_declaration=True)
        (directory / 'benchmark.json').write_text(json.dumps(evidence, indent=2)+'\n')
        record['finished_at'] = datetime.now(timezone.utc).isoformat()
        report_path.write_text(json.dumps(record, indent=2)+'\n')
    print(f'PASS: fast {config_path.stem} {benchmark["profile"]}: {measured["cycles"]} cycles, native execution {elapsed:.3f} s')
    return directory
