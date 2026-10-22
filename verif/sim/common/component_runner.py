#!/usr/bin/env python3
"""GNU Make helper for component simulation and lint; select a config/sim manifest."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

import yaml

from elf_image import expected_traps, load_elf
from interrupts import interrupt_plan
from hw_config import BOOLEAN_PARAMS, load_configuration, parameters_for_component, write_header


ROOT = Path(__file__).resolve().parents[3]

# Keep owned .v sources in Verilog-2005; imported IP and verification may use .sv.
HDL_LANGUAGE_ARGS = ["--language", "1364-2005", "+1800-2017ext+sv"]


def load_component(name, directory=None):
    """Read declarative component settings without component-specific Python."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ValueError(f"invalid component name: {name!r}")
    directory = directory if directory is not None else ROOT / "config/sim"
    path = directory / f"{name}.yml"
    if not path.is_file():
        raise ValueError(f"unknown component {name!r}: missing {path}")
    component = yaml.safe_load(path.read_text())
    expected = {"top_module", "bender_target", "test_module", "parameters", "tests"}
    if (not isinstance(component, dict) or not expected <= set(component) or
            set(component) - expected - {'requires_elf', 'bender_dependencies', 'bender_dependencies_if', 'bender_targets'}):
        raise ValueError(f"component manifest must contain {sorted(expected)}; "
                         "optional: requires_elf, bender_dependencies, bender_dependencies_if, bender_targets")
    for key in ('requires_elf', 'bender_dependencies'):
        if key in component and type(component[key]) is not bool:
            raise ValueError(f'component {key} must be a boolean')
    if 'bender_dependencies_if' in component:
        selector = component['bender_dependencies_if']
        if not isinstance(selector, str) or selector not in BOOLEAN_PARAMS or selector not in component['parameters']:
            raise ValueError('bender_dependencies_if must name a declared boolean hardware parameter')
    targets = component.get('bender_targets', [])
    if (not isinstance(targets, list) or
            any(not isinstance(value, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*', value)
                for value in targets) or len(set(targets)) != len(targets)):
        raise ValueError('component bender_targets must contain unique target identifiers')
    for key, pattern in {
        "top_module": r"[A-Za-z_][A-Za-z0-9_$]*",
        "bender_target": r"[A-Za-z_][A-Za-z0-9_-]*",
        "test_module": r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*",
    }.items():
        if not isinstance(component[key], str) or not re.fullmatch(pattern, component[key]):
            raise ValueError(f"invalid component {key}: {component[key]!r}")
    for key, pattern in {"parameters": r"[A-Z][A-Z0-9_]*", "tests": r"[A-Za-z_]\w*"}.items():
        values = component[key]
        if (not isinstance(values, list) or (key == "tests" and not values) or
                any(not isinstance(value, str) or not re.fullmatch(pattern, value)
                    for value in values) or len(set(values)) != len(values)):
            raise ValueError(f"component {key} must contain unique identifiers; tests must be nonempty")
    if "all" in component["tests"]:
        raise ValueError("component test name 'all' is reserved for suite selection")
    return component


def check_results(path, expected_tests):
    """Reject missing, skipped, failed, or unexpected tests, not just a bad exit."""
    cases = ET.parse(path).findall(".//testcase")
    names = [case.get("name") for case in cases]
    if sorted(names) != sorted(expected_tests):
        raise RuntimeError(f"test results do not match selection: expected {expected_tests}, got {names}")
    if any(case.find(tag) is not None
           for case in cases for tag in ("failure", "error", "skipped")):
        raise RuntimeError("regression has failed or skipped tests")
    return len(cases)


def command_output(command):
    return subprocess.check_output(command, cwd=ROOT, text=True).strip()


def bender_dependencies_enabled(component, parameters):
    selector = component.get('bender_dependencies_if')
    if selector is not None and (parameters is None or selector not in parameters):
        raise ValueError(f'missing dependency selector parameter: {selector}')
    return component.get('bender_dependencies', False) or bool(selector and parameters[selector])


def bender_source_options(component, simulator='verilator', parameters=None):
    """Include imported HDL only for manifests that explicitly require it."""
    options = ['-t', component['bender_target'], '-t', simulator]
    for target in component.get('bender_targets', []):
        options += ['-t', target]
    if not bender_dependencies_enabled(component, parameters):
        options.append('--no-deps')
    return options


def order_control_files(sources):
    """Read Verilator file-specific controls before their affected HDL files."""
    return ([path for path in sources if path.suffix == '.vlt'] +
            [path for path in sources if path.suffix != '.vlt'])


def check_reference(run_dir, config, reference_info):
    from spike import check_run
    try:
        return check_run(run_dir, config, reference_info)
    except BaseException as error:
        # A successful HDL run alone must not appear as a passing differential
        # run in JUnit or the aggregate report.
        results = run_dir / 'results.xml'
        tree = ET.parse(results)
        case = tree.find('.//testcase')
        ET.SubElement(case, 'failure', type='SpikeDifferential', message=str(error)).text = str(error)
        tree.write(results, encoding='unicode', xml_declaration=True)
        raise


def bender_include_dirs(source_tree, root=ROOT):
    """Collect selected Bender source-group include paths in declaration order."""
    directories = []

    def visit(group):
        for value in group.get("include_dirs", []):
            directory = (root / value).resolve()
            if not directory.is_dir():
                raise ValueError(f"Bender include directory does not exist: {directory}")
            if directory not in directories:
                directories.append(directory)
        for child in group.get("files", []):
            if isinstance(child, dict):
                visit(child)

    visit(source_tree)
    return directories


def simulator_build_key(sources, headers, includes, parameters, top, simulator, waves, generated):
    def location(path):
        return 'generated/' + str(path.relative_to(generated)) if path.is_relative_to(generated) else str(path)

    inputs = {
        'sources': [(str(p), hashlib.sha256(p.read_bytes()).hexdigest()) for p in sources],
        'headers': [(location(p), hashlib.sha256(p.read_bytes()).hexdigest()) for p in headers],
        'includes': [location(p) for p in includes],
        'parameters': parameters, 'top': top, 'language': HDL_LANGUAGE_ARGS,
        'simulator': simulator, 'waves': waves,
    }
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()


def main(argv=None, shared_build=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("test", "lint"), default="test")
    parser.add_argument("--component", required=True, help="manifest name under config/sim/")
    parser.add_argument("--config", default="rv32i")
    parser.add_argument("--sim", choices=("verilator",), default="verilator")
    parser.add_argument("--bender", default="bender")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--test", default="all", help="all or a test named by the component manifest")
    parser.add_argument("--waves", type=int, choices=(0, 1), default=0)
    parser.add_argument("--elf", help="statically linked RV32 ELF for a requires_elf component")
    parser.add_argument('--label', help='scenario label for an ELF suite member')
    parser.add_argument("--max-cycles", type=int, default=100000, help="ELF execution watchdog")
    parser.add_argument('--reference', choices=('none', 'spike'), default='none')
    parser.add_argument('--spike', default='', help='external Spike executable; otherwise SPIKE, RISCV/bin, PATH')
    parser.add_argument('--imem-latency', type=int, help='fixed grant-to-response cycles; requires dmem latency')
    parser.add_argument('--dmem-latency', type=int, help='fixed grant-to-response cycles; requires imem latency')
    parser.add_argument('--benchmark', action='store_true', help='measure the ELF-bound benchmark window')
    args = parser.parse_args(argv)
    component = load_component(args.component)
    if args.test != "all" and args.test not in component["tests"]:
        raise ValueError(f"unknown test {args.test!r} for {args.component}; "
                         f"choose all or one of {component['tests']}")
    selected_tests = component["tests"] if args.test == "all" else [args.test]
    config_path = Path(args.config)
    if not config_path.is_file():
        config_path = ROOT / "config" / f"{args.config}.yml"
    config_path = config_path.resolve()
    catalog = json.loads((ROOT / "config/selectors.json").read_text())
    config = load_configuration(config_path, catalog)
    for tool in (args.bender, args.sim):
        if not shutil.which(tool):
            raise ValueError(f"required tool not found: {tool}; provide it externally")
    parameters = parameters_for_component(config, component["parameters"], catalog)
    if args.max_cycles <= 0:
        raise ValueError('--max-cycles must be positive')
    elf_path = None
    image = None
    if args.action == 'test' and component.get('requires_elf', False):
        if not args.elf:
            raise ValueError('this component requires ELF=<path>; build with make sw or supply an ELF')
        elf_path = Path(args.elf).resolve()
        image = load_elf(elf_path)
        image.validate_core(parameters)
        image.tohost  # Validate completion storage before compiling the simulator.
        declared_traps = expected_traps(image)
        declared_interrupts = interrupt_plan(image,parameters)
    elif args.elf:
        raise ValueError('ELF is only supported for tests of a requires_elf component')
    memory = None
    if args.imem_latency is not None or args.dmem_latency is not None:
        if elf_path is None or any(type(v) is not int or not 1 <= v <= 1000000
                                   for v in (args.imem_latency, args.dmem_latency)):
            raise ValueError('fixed memory timing requires an ELF and both positive latencies')
        memory = dict(imem_latency=args.imem_latency, dmem_latency=args.dmem_latency)
    benchmark = None
    if args.benchmark:
        if elf_path is None or memory is None or args.component != 'core_elf':
            raise ValueError('benchmark measurement requires core_elf with fixed memory timing')
        from benchmark_measure import marker_addresses, software_compatible
        marker_addresses(image)
        software = json.loads((elf_path.parent / 'build.json').read_text())
        if (software.get('status') != 'passed' or software.get('elf_sha256') != hashlib.sha256(elf_path.read_bytes()).hexdigest()
                or not software_compatible(software.get('parameters', {}), config)
                or not isinstance(software.get('benchmark'), dict)):
            raise ValueError('benchmark needs successful matching ELF build metadata')
        benchmark = software['benchmark']
        if benchmark.get('memory') != memory:
            raise ValueError('benchmark memory profile differs from build metadata')
        for name, expected in software['source_sha256'].items():
            source = ROOT / name
            if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
                raise ValueError(f'benchmark build input changed: {name}; rebuild')
    reference_info = None
    if args.reference == 'spike':
        if elf_path is None:
            raise ValueError('Spike comparison requires ELF execution')
        from spike import discover_spike, identify_spike
        reference_info = identify_spike(discover_spike(args.spike))
    component_path = Path('benchmark') / benchmark['name'] if benchmark else Path(args.component)
    run_dir = ROOT / "build" / f"uquintus-{config_path.stem}" / args.sim / component_path / (
        f"{args.action}-{args.test}-seed{args.seed}-{uuid.uuid4().hex[:12]}")
    run_dir.mkdir(parents=True)
    write_header(catalog, run_dir / "include")
    (run_dir / "config.yml").write_text(yaml.safe_dump(config, sort_keys=False))
    (run_dir / "component.yml").write_text(yaml.safe_dump(component, sort_keys=False))
    (run_dir / "selectors.json").write_text(json.dumps(catalog, indent=2) + "\n")
    source_options = bender_source_options(component, args.sim, parameters)
    sources_text = command_output([args.bender, "script", "flist", *source_options])
    sources = [(ROOT / line.strip()).resolve() for line in sources_text.splitlines()
               if line.strip() and not line.lstrip().startswith("//")]
    if not sources or any(not path.is_file() for path in sources):
        raise ValueError("Bender did not produce an existing HDL source list")
    sources = order_control_files(sources)
    (run_dir / "sources.f").write_text(''.join(str(path) + '\n' for path in sources))
    source_tree_text = command_output([args.bender, "sources", *source_options])
    (run_dir / "bender_sources.json").write_text(source_tree_text + "\n")
    include_dirs = [run_dir / "include", *bender_include_dirs(json.loads(source_tree_text))]
    headers = sorted({header for directory in include_dirs for suffix in ('*.vh', '*.svh')
                      for header in directory.rglob(suffix)})
    metadata = {
        "component": args.component, "action": args.action, "test": args.test,
        'target': args.sim,
        "seed": args.seed, "configuration": str(config_path), "parameters": parameters,
        "component_manifest": component,
        "hdl_language_args": HDL_LANGUAGE_ARGS,
        "python": sys.version, "simulator": command_output([args.sim, "--version"]),
        "bender": command_output([args.bender, "--version"]),
        "source_sha256": {str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path):
                          hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sources},
        "include_dirs": [str(directory) for directory in include_dirs],
        "header_sha256": {str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path):
                          hashlib.sha256(path.read_bytes()).hexdigest() for path in headers},
        "status": "running",
        'started_at': datetime.now(timezone.utc).isoformat(),
    }
    if bender_dependencies_enabled(component, parameters):
        lock = ROOT / 'Bender.lock'
        shutil.copyfile(lock, run_dir / 'Bender.lock')
        metadata['bender_lock_sha256'] = hashlib.sha256(lock.read_bytes()).hexdigest()
    metadata_path = run_dir / "run.json"
    if args.label:
        if elf_path is None:
            raise ValueError('--label requires ELF execution')
        metadata['selection'] = args.label
    extra_env = {"UQU_COMPONENT_PARAMS": json.dumps(parameters)}
    # Explicitly clear these for ordinary tests, including suites which reuse
    # one simulator process configuration after a benchmark invocation.
    extra_env.update(UQU_MEMORY_TIMING=json.dumps(memory), UQU_BENCHMARK=json.dumps(benchmark))
    if elf_path is not None:
        program = run_dir / 'program.elf'
        shutil.copyfile(elf_path, program)
        metadata['elf'] = {
            'source': str(elf_path), 'sha256': hashlib.sha256(program.read_bytes()).hexdigest(),
            'entry': image.entry, 'tohost': image.tohost, 'max_cycles': args.max_cycles,
            'expected_traps': declared_traps,
            'interrupt_plan': declared_interrupts,
            'segments': [{'address': s.address, 'file_size': len(s.data),
                          'memory_size': s.size, 'flags': s.flags} for s in image.segments],
        }
        build_metadata = elf_path.parent / 'build.json'
        if build_metadata.is_file():
            software = json.loads(build_metadata.read_text())
            if (software.get('status') == 'passed' and
                    software.get('elf_sha256') == metadata['elf']['sha256']):
                shutil.copyfile(build_metadata, run_dir / 'software-build.json')
                for key in ('compiler', 'compiler_info', 'upstream'):
                    if key in software:
                        metadata[key] = software[key]
                metadata['source_sha256'].update(software.get('source_sha256', {}))
                metadata['input_scope'] = 'HDL, headers and recorded software sources'
                compiler = software.get('compiler_info')
                if compiler:
                    metadata['context'] = {key: compiler[key] for key in ('family', 'version', 'target', 'march', 'abi')}
                    if software.get('upstream'):
                        metadata['context']['suite_revision'] = software['upstream']['revision']
        extra_env.update(UQU_ELF=str(program), UQU_MAX_CYCLES=str(args.max_cycles))
    if memory:
        metadata.setdefault('context', {})['memory'] = dict(memory,
            grants='immediate', fence_ack='immediate', ports='independent', response_errors='none')
    if benchmark:
        from bpu_stats import SCOPE as BPU_SCOPE
        metadata['benchmark'] = benchmark
        metadata.setdefault('context', {}).update(benchmark=benchmark,
            bpu_statistics=BPU_SCOPE,
            execution_mode='checked', validation_scope='instruction_oracle_rvfi_counters_and_crc',
            measurement='retirement edges (start, stop]; timer call overhead included')
        # Python monitors/agents are measurement inputs too.
        for directory in (ROOT / 'verif/sim/common', ROOT / 'verif/sim/core', ROOT / 'verif/sim/core_elf'):
            for source in directory.glob('*.py'):
                metadata['source_sha256'][str(source.relative_to(ROOT))] = hashlib.sha256(source.read_bytes()).hexdigest()
    if reference_info:
        metadata['reference'] = reference_info
        metadata['input_scope'] = 'HDL, headers, recorded software sources, native oracle and reference adapter/pin'
        metadata.setdefault('context', {})['reference'] = 'spike:' + reference_info['executable_sha256']
        metadata['context']['reference_profile'] = reference_info['profile']
        for path in (ROOT / 'verif/sim/common/spike.py', ROOT / 'verif/reference/spike.lock.json',
                     ROOT / 'verif/sim/common/spike_zfinx.py',
                     ROOT / 'verif/sim/common/fpu_model.py',
                     ROOT / 'verif/sim/common/interrupts.py', ROOT / 'verif/sim/common/timing.py', ROOT / 'verif/sim/common/spike_irq.py',
                     ROOT / 'verif/sim/common/csregfile_model.py', ROOT / 'verif/sim/common/rvfi_csrs.py',
                     ROOT / 'verif/sim/core/core_env.py', ROOT / 'verif/sim/core_elf/test_uqu_elf.py',
                     ROOT / 'verif/reference/spike_irq.cc'):
            metadata['source_sha256'][str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Artifacts: {run_dir}", flush=True)
    try:
        if args.action == "lint":
            command = [args.sim, "--lint-only", *HDL_LANGUAGE_ARGS,
                       "--top-module", component["top_module"]]
            command += [f"-I{directory}" for directory in include_dirs]
            command += [f"-G{key}={value}" for key, value in parameters.items()]
            command += [str(path) for path in sources]
            result = subprocess.run(command, cwd=run_dir, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            (run_dir / "lint.log").write_text(result.stdout)
            if result.returncode:
                print(result.stdout, file=sys.stderr)
                raise RuntimeError("Verilator lint failed")
        else:
            # Pinned API: cocotb 1.9.2. No installation is performed by this flow.
            from cocotb.runner import get_runner
            metadata["packages"] = {name: importlib.metadata.version(name)
                                    for name in ("cocotb", "pyuvm", "PyYAML")}
            build_key = simulator_build_key(sources, headers, include_dirs, parameters,
                component['top_module'], metadata['simulator'], args.waves, run_dir / 'include')
            if shared_build is not None and shared_build.get('key') == build_key:
                runner = shared_build['runner']
                build_dir = shared_build['directory']
                metadata['reused_simulator_build'] = str(build_dir)
            else:
                runner = get_runner(args.sim)
                build_dir = run_dir / 'obj'
                runner.build(
                    verilog_sources=sources, includes=include_dirs,
                    parameters=parameters, hdl_toplevel=component["top_module"],
                    build_args=HDL_LANGUAGE_ARGS,
                    build_dir=build_dir, timescale=("1ns", "1ps"),
                    waves=bool(args.waves), log_file=run_dir / "build.log",
                )
                if shared_build is not None:
                    shared_build.update(key=build_key, runner=runner, directory=build_dir)
            test_dir = ROOT / "verif/sim" / args.component
            sys.path.insert(0, str(test_dir))
            results = run_dir / "results.xml"
            runner.test(
                hdl_toplevel=component["top_module"], test_module=component["test_module"],
                testcase=",".join(selected_tests),
                seed=args.seed, build_dir=build_dir, test_dir=run_dir,
                results_xml=str(results), waves=bool(args.waves),
                extra_env=extra_env,
                log_file=run_dir / "simulation.log",
            )
            native_passed = check_results(results, selected_tests)
            if reference_info:
                metadata['differential'] = check_reference(run_dir, config, reference_info)
            metadata['tests_passed'] = native_passed
        if benchmark:
            evidence = json.loads((run_dir / 'benchmark.json').read_text())
            if evidence.get('status') != 'passed':
                raise RuntimeError('benchmark has no passing measurement evidence')
            from bpu_stats import validate as validate_bpu
            validate_bpu(evidence.get('bpu_statistics'), config, evidence['window']['retired'])
        metadata["status"] = "passed"
    except BaseException as error:
        metadata["status"] = "failed"
        error.run_dir = run_dir
        raise
    finally:
        metadata['finished_at'] = datetime.now(timezone.utc).isoformat()
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
        if benchmark:
            evidence_path = run_dir / 'benchmark.json'
            evidence = json.loads(evidence_path.read_text()) if evidence_path.is_file() else {}
            metrics = []
            if metadata['status'] == 'passed':
                from bpu_stats import validate as validate_bpu, metrics as bpu_metrics
                bpu = validate_bpu(evidence['bpu_statistics'], config, evidence['window']['retired'])
                for name, value, unit in (
                    ('benchmark_cycles', evidence['window']['cycles'], 'cycles'),
                    ('benchmark_retired', evidence['window']['retired'], 'instructions'),
                    ('benchmark_cpi', evidence['window']['cpi'], 'cycles/instruction'),
                    ('cycles_per_iteration', evidence['result']['cycles_per_iteration'], 'cycles/iteration'),
                    ('elf_load_bytes', sum(s.size for s in image.segments), 'bytes'),
                    ('executable_segment_bytes', sum(len(s.data) for s in image.segments if s.flags & 1), 'bytes')):
                    metrics.append(dict(name=name, value=value, unit=unit))
                metrics += bpu_metrics(bpu)
            report = dict(metadata, schema_version=1, kind='benchmark', configuration_scope='core',
                          configuration=dict(name=config_path.stem, parameters=config),
                          selection=args.label or benchmark['name'] + '-' + benchmark['profile'],
                          workload=metadata['elf']['sha256'], metrics=metrics,
                          results_file='results.xml',
                          artifacts=['benchmark.json', 'benchmark.log', 'bpu-stats.json', 'run.json'])
            (run_dir / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f"PASS: {args.action} {config_path.stem} {args.test} seed={args.seed}")
    return run_dir


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError, yaml.YAMLError,
            subprocess.CalledProcessError) as error:
        sys.exit(str(error))
