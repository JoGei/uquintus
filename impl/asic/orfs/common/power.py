#!/usr/bin/env python3
"""Estimate workload power with repaired-cell activity and embedded OpenSTA."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

from synth import ROOT, COMMON, executable, flow_directory, key, output
from benchmark_fast import run_fast
from hw_config import load_configuration
from power_measure import annotation, check_activity_clock, energy, vcd_window


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''): result.update(chunk)
    return result.hexdigest()


def tcl(value):
    """One Tcl list element, including spaces and literal substitutions."""
    value = str(value)
    return '"' + value.translate(str.maketrans({'\\': '\\\\', '"': '\\"', '$': '\\$', '[': '\\[', ']': '\\]', '\n': '\\n', '\r': '\\r'})) + '"'


def gate_include(netlist):
    """Connect the actual flattened top to the RTL oracle's exact input pins."""
    ports = re.findall(r'^\s*(input|output)\s+(\[[^\]]+\]\s*)?(\w+)\s*;', netlist, re.M)
    if not ports or 'module uqu_core ' not in netlist:
        raise ValueError('expected flattened ORFS uqu_core netlist with explicit port declarations')
    lines, connections = [], []
    for direction, width, name in ports:
        if direction == 'input':
            connections.append(f'.{name}(u_core.{name})')
        else:
            lines.append(f'wire {width}power_{name};')
            connections.append(f'.{name}(power_{name})')
    lines.append('uqu_power_core u_gate (\n' + ',\n'.join(connections) + '\n);')
    checks = [('imem_req_o', '1\'b1'), ('imem_addr_o', 'imem_req_o'),
              ('dmem_req_o', '1\'b1'), ('dmem_we_o', 'dmem_req_o'),
              ('dmem_addr_o', 'dmem_req_o'), ('dmem_be_o', 'dmem_req_o'),
              ('dmem_wdata_o', 'dmem_req_o && dmem_we_o'),
              ('fence_req_o', '1\'b1'), ('fencei_req_o', '1\'b1')]
    lines.append('always @(posedge clk_i) if (rst_ni) begin')
    for name, qualifier in checks:
        lines.append(f'if (({qualifier}) && power_{name} !== u_core.{name}) '
                     f'$fatal(1, "placed-netlist/RTL mismatch: {name}");')
    lines.append('end')
    return '\n'.join(lines) + '\n'


def functional_netlist(netlist, models):
    ports = {}
    for name, body in re.findall(r'module\s+(\w+)\b(.*?)endmodule', models, re.S):
        ports[name] = {port: direction for direction, port in re.findall(
            r'^\s*(input|output)\s+(?:\[[^\]]+\]\s*)?(\w+)\s*;', body, re.M)}

    def instance(match):
        cell, name, connections = match.groups()
        # No-signal physical-only cells remain in the STA database.
        if not connections.strip(): return ''
        if cell not in ports: raise ValueError('missing functional cell model: ' + cell)
        connected = set(re.findall(r'\.(\w+)\s*\(', connections))
        missing = set(ports[cell]) - connected
        if any(ports[cell][port] != 'output' for port in missing):
            raise ValueError('unconnected cell input: ' + name)
        for port in sorted(missing): connections += ', .' + port + '()'
        return cell + ' ' + name + '(' + connections + ');'

    renamed = netlist.replace('module uqu_core ', 'module uqu_power_core ', 1)
    return re.sub(r'^\s*((?!module\b)\w+)\s+(\\\S+\s+|\w+\s*)\((.*?)\);', instance, renamed, flags=re.M | re.S)


def validate_implementation(directory):
    record = json.loads((directory / 'report.json').read_text())
    if (record.get('kind') != 'synthesis' or record.get('status') != 'passed' or
            record.get('component') != 'uqu_core' or record['context'].get('stage') != 'placed_pre_cts'):
        raise ValueError('power requires a successful core implementation through repaired placement')
    # Match the functional design, not unrelated flow/document changes since
    # synthesis. The immutable database/netlist are hashed in the new record.
    for name, expected in record['input_sha256'].items():
        path = ROOT / name
        if (name.startswith(('src/', '.bender/')) and path.suffix in ('.v', '.sv', '.vh', '.svh')):
            if not path.is_file() or digest(path) != expected:
                raise ValueError('implementation RTL changed; regenerate implementation: ' + name)
    for name, expected in record['context']['mapping_libraries'].items():
        if digest(Path(name)) != expected:
            raise ValueError('implementation Liberty changed: ' + name)
    catalog = json.loads((ROOT / 'config/selectors.json').read_text())
    config = load_configuration(directory / 'config.yml', catalog)
    if config != record['configuration']['parameters']:
        raise ValueError('implementation configuration differs from its recorded parameters')
    if config['XIF'] or config['DEBUG']:
        raise ValueError('power benchmark currently requires XIF=0 and DEBUG=0')
    return record, config


def validate_activity(directory, program, config, generated, period_ps):
    record = json.loads((directory / 'report.json').read_text())
    if (record.get('kind') != 'benchmark' or record.get('status') != 'passed' or
            record['configuration']['parameters'] != config or record.get('workload') != digest(program) or
            record['context'].get('activity', {}).get('clock_period_ps') != period_ps):
        raise ValueError('reused activity requires the same successful benchmark, hardware, ELF and period')
    for path in generated:
        matches = [value for name, value in record['source_sha256'].items() if Path(name).name == path.name]
        if matches != [digest(path)]:
            raise ValueError('reused activity netlist or cell models differ: ' + path.name)
    evidence = json.loads((directory / 'benchmark.json').read_text())
    native = json.loads((directory / 'native.json').read_text())
    if evidence.get('status') != 'passed' or native.get('status') != 'passed' or not (directory / 'activity.vcd.gz').is_file():
        raise ValueError('reused activity has no successful benchmark or waveform evidence')
    return directory


def run(args):
    implementation = Path(args.implementation).resolve()
    impl, config = validate_implementation(implementation)
    period = float(impl['context']['clock_period_ns'])
    period_ps = round(period * 1000)
    if period_ps <= 0 or period_ps % 2 or not math.isclose(period_ps, period * 1000, abs_tol=1e-8):
        raise ValueError('power clock period must be representable as positive even picoseconds')
    if args.jobs < 1 or not 0 < args.min_coverage <= 1:
        raise ValueError('JOBS must be positive; coverage must be in (0,1]')
    flow = flow_directory(args.orfs_root)
    yosys = executable(args.yosys, 'yosys', flow.parent / 'tools/install/yosys/bin/yosys')
    openroad = executable(args.openroad, 'openroad', flow.parent / 'tools/install/OpenROAD/bin/openroad')
    platform = impl['context']['platform']
    results = implementation / 'results' / platform / 'uqu_core/base'
    database = results / '3_6_place_repair_timing.odb'
    netlist = implementation / 'physical/uqu_placed.v'
    rc = flow / 'platforms' / platform / 'setRC.tcl'
    sdc = implementation / 'constraints.sdc'
    for path in (database, netlist, rc, sdc):
        if not path.is_file():
            raise ValueError('missing power input: ' + str(path))
    # RC parameters are part of the synthesis run's platform input evidence.
    for path in (rc, sdc):
        expected = impl['input_sha256'].get(key(path))
        if not expected or expected != digest(path):
            raise ValueError('physical timing input changed or unrecorded: ' + str(path))
    directory = implementation / ('power-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
    directory.mkdir()
    record = dict(schema_version=1, kind='power', status='running', configuration_scope='core',
        configuration=impl['configuration'], component='uqu_core', target='opensta_' + platform,
        selection='benchmark_activity', started_at=datetime.now(timezone.utc).isoformat(),
        context=dict(platform=platform, clock_period_ns=period, stage='placed_pre_cts',
            clock_model='ideal_pre_cts', sta_interconnect='placement_estimated', activity='zero_delay_gate_vcd',
            coverage_minimum=args.min_coverage, power_scope='core cells and placement-estimated nets; external memories excluded',
            timing_qualified=all(m['value'] >= 0 for m in impl['metrics'] if m['name'] in ('setup_worst_slack', 'hold_worst_slack')),
            limitations='No routed parasitics, clock-tree implementation, delay glitches, external memories or SoC power.'),
        implementation=key(implementation / 'report.json'), metrics=[], artifacts=[], input_sha256={})
    report = directory / 'report.json'
    print('Power artifacts:', directory, flush=True)
    try:
        libraries = list(impl['context']['mapping_libraries'])
        (directory / 'uqu_power_gate.vh').write_text(gate_include(netlist.read_text()))
        (directory / 'activity.vlt').write_text('`verilator_config\ntracing_off -scope "*u_core*" -levels 99\ntracing_off -scope "*u_bpu_monitor*" -levels 99\n')
        # Liberty supplies portable Boolean/sequential models. A used cell with
        # a missing function is rejected by the generated-model check.
        script = '\n'.join('read_liberty -ignore_miss_func -ignore_miss_dir ' + tcl(p) for p in libraries)
        script += '\nwrite_verilog -noattr ' + tcl(directory / 'cells.v') + '\n'
        (directory / 'cells.ys').write_text(script)
        (directory / 'cells.log').write_text(output([str(yosys), '-Q', '-T', '-s', str(directory / 'cells.ys')]))
        (directory / 'uqu_power_core.v').write_text(functional_netlist(netlist.read_text(), (directory / 'cells.v').read_text()))
        record['tools'] = dict(openroad=output([str(openroad), '-version']), yosys=output([str(yosys), '-V']),
                               openroad_sha256=digest(openroad), yosys_sha256=digest(yosys))
        inputs = [database, netlist, rc, sdc, Path(args.elf).resolve(), implementation / 'report.json',
                  COMMON / 'power.tcl', Path(__file__), ROOT / 'verif/sim/benchmark/activity_vcd.h',
                  ROOT / 'verif/sim/common/power_measure.py', *map(Path, libraries)]
        record['input_sha256'] = {key(p): digest(p) for p in inputs}
        record['context']['libraries'] = impl['context']['mapping_libraries']
        report.write_text(json.dumps(record, indent=2) + '\n')
        activity_config = directory / (impl['configuration']['name'] + '.yml')
        activity_config.write_bytes((implementation / 'config.yml').read_bytes())
        generated = [directory / 'uqu_power_core.v', directory / 'cells.v']
        if args.activity_run:
            activity_run = validate_activity(Path(args.activity_run).resolve(), Path(args.elf).resolve(), config, generated, period_ps)
        else:
            activity_run = run_fast(args.elf, activity_config, config, bender=args.bender, jobs=args.jobs,
                power_activity=dict(sources=generated, include=directory,
                                    trace_config=directory / 'activity.vlt', period_ps=period_ps))
        benchmark = json.loads((activity_run / 'benchmark.json').read_text())
        record['benchmark_report'] = key(activity_run / 'report.json')
        benchmark_record = json.loads((activity_run / 'report.json').read_text())
        record['workload'] = benchmark_record['workload']
        record['context'].update(benchmark=benchmark_record['context']['benchmark'],
                                 memory=benchmark_record['context']['memory'], tools=record['tools'])
        record['input_sha256'].update(benchmark_record['source_sha256'])
        activity = activity_run / 'activity.vcd.gz'
        measured = benchmark['window']
        # Scan the waveform's time domain while OpenSTA independently reads
        # activity; both checks must pass before any power result qualifies.
        with ThreadPoolExecutor(max_workers=1) as activity_pool:
            waveform_window = activity_pool.submit(vcd_window, activity)
            record['input_sha256'][key(activity)] = digest(activity)
            variables = dict(uqu_libraries=libraries, uqu_database=database, uqu_sdc=sdc, uqu_rc=rc,
                             uqu_activity=activity, uqu_output=directory)
            (directory / 'inputs.tcl').write_text('\n'.join('set ' + name + ' ' +
                ('[list ' + ' '.join(tcl(p) for p in value) + ']' if isinstance(value, list) else tcl(value))
                for name, value in variables.items()) + '\n')
            command = [str(openroad), '-no_init', '-threads', str(args.jobs), '-exit', str(COMMON / 'power.tcl')]
            record['command'] = command
            record['command_env'] = dict(UQU_POWER_INPUTS=str(directory / 'inputs.tcl'))
            with (directory / 'opensta.log').open('w') as log:
                result = subprocess.run(command, env=dict(os.environ, **record['command_env']),
                                        stdout=log, stderr=subprocess.STDOUT, cwd=directory)
            if result.returncode:
                raise RuntimeError('OpenSTA power failed; see opensta.log')
            check_activity_clock((directory / 'opensta.log').read_text())
            first, last = waveform_window.result()
        if first != 0 or last != measured['cycles'] * period_ps:
            raise ValueError(f'VCD window disagrees with benchmark: {first}..{last} ps')
        record['context'].update(benchmark_window=measured, activity_duration_ps=last,
                                 activity_scope='TOP/uqu_benchmark_tb/u_gate')
        coverage = annotation((directory / 'activity-annotation.rpt').read_text(), args.min_coverage)
        powers = json.loads((directory / 'opensta-power.json').read_text())
        values = energy(powers, measured['cycles'], measured['retired'], period)
        evidence = dict(schema_version=1, status='passed', coverage=coverage, power=powers,
                        metrics=values, benchmark_window=measured, clock_period_ns=period)
        (directory / 'power.json').write_text(json.dumps(evidence, indent=2) + '\n')
        record['context']['activity_coverage'] = coverage
        record['metrics'] = [dict(name=name, value=value, unit=('W' if name.endswith('_w') else 's' if name.endswith('_s')
                              else 'J/instruction' if name.endswith('_instruction_j') else 'J')) for name, value in values.items()]
        record['status'] = 'passed'
        print(f"PASS: dynamic {values['dynamic_power_w']*1000:.3f} mW, leakage {values['leakage_power_w']*1000:.3f} mW; "
              f"dynamic energy {values['dynamic_energy_j']*1e6:.3f} uJ; measured pins {coverage['measured_pin_fraction']:.2%}")
    except BaseException as error:
        record.update(status='failed', detail=str(error))
        raise
    finally:
        record['artifacts'] = [p.name for p in directory.iterdir() if p.is_file() and p != report]
        record['finished_at'] = datetime.now(timezone.utc).isoformat()
        report.write_text(json.dumps(record, indent=2) + '\n')
    return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--implementation', required=True, help='retained make impl run directory')
    parser.add_argument('--elf', required=True, help='built, self-checking benchmark ELF')
    parser.add_argument('--activity-run', help='reuse a successful, identical gate-activity benchmark directory')
    parser.add_argument('--orfs-root', default=os.environ.get('ORFS_ROOT', ''))
    parser.add_argument('--yosys', default=os.environ.get('YOSYS_EXE', ''))
    parser.add_argument('--openroad', default=os.environ.get('OPENROAD_EXE', ''))
    parser.add_argument('--bender', default='bender')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--min-coverage', type=float, default=.99)
    args = parser.parse_args()
    try:
        run(args)
    except (ValueError, RuntimeError, OSError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
