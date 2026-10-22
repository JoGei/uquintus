"""Execute a manifest of independent ELF runs with one compatible simulator build."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
import uuid
import xml.etree.ElementTree as ET

from component_runner import main as run_component
from elf_image import load_elf


def validate_suite(path, config):
    data = json.loads(path.read_text())
    if (data.get('schema_version') != 1 or data.get('status') != 'passed' or
            data.get('parameters') != config or not data.get('programs')):
        raise ValueError('suite must have successful builds, matching full configuration and nonempty programs')
    seen = set()
    for program in data['programs']:
        name = program['name']
        if not re.fullmatch('[A-Za-z0-9_-]+', name) or name in seen:
            raise ValueError('suite program names must be unique safe identifiers')
        seen.add(name)
        elf = Path(program['path'])
        if hashlib.sha256(elf.read_bytes()).hexdigest() != program['sha256']:
            raise ValueError(f'suite ELF changed since build: {name}')
        image = load_elf(elf)
        image.validate_core(config)
        image.tohost
    return data


def run_suite(path, config_path, config, *, root, seed=1, simulator='verilator',
              bender='bender', max_cycles=100000, waves=0, reference='none', spike=''):
    if max_cycles <= 0:
        raise ValueError('suite max_cycles must be positive')
    suite = validate_suite(path, config)
    reference_info = None
    if reference == 'spike':
        from spike import discover_spike, identify_spike
        reference_info = identify_spike(discover_spike(spike))
    directory = root / 'build' / f'uquintus-{config_path.stem}' / simulator / 'riscv-tests' / (
        f'suite-seed{seed}-{uuid.uuid4().hex[:12]}')
    directory.mkdir(parents=True)
    (directory / 'suite.json').write_text(json.dumps(suite, indent=2) + '\n')
    xml = ET.Element('testsuites')
    cases = ET.SubElement(xml, 'testsuite', name=suite['suite'])
    record = {'schema_version': 1, 'kind': 'test', 'component': 'riscv-tests',
              'target': simulator, 'configuration': {'name': config_path.stem, 'parameters': config},
              'selection': suite['selection'], 'seed': seed, 'status': 'running',
              'started_at': datetime.now(timezone.utc).isoformat(),
              'compiler_info': suite['compiler_info'], 'upstream': suite['upstream'],
              'workload': hashlib.sha256(path.read_bytes()).hexdigest(),
              'context': {'suite_revision': suite['upstream']['revision'],
                          'compiler_family': suite['compiler_info']['family'],
                          'compiler_version': suite['compiler_info']['version'],
                          'march': suite['compiler_info']['march'], 'abi': suite['compiler_info']['abi']},
              'results_file': 'suite-results.xml', 'artifacts': ['suite-results.xml', 'suite.json'],
              'required_tests': [p['name'] for p in suite['programs']],
              'excluded_tests': suite['excluded'],
              'metrics': [], 'runs': []}
    if reference_info:
        record['reference'] = reference_info
        record['context']['reference'] = 'spike:' + reference_info['executable_sha256']
    failures, shared_build = [], {}

    def save():
        (directory / 'report.json').write_text(json.dumps(record, indent=2) + '\n')
        ET.ElementTree(xml).write(directory / 'suite-results.xml', encoding='unicode', xml_declaration=True)

    save()
    try:
        for program in suite['programs']:
            start = time.monotonic()
            case = ET.SubElement(cases, 'testcase', name=program['name'])
            try:
                if hashlib.sha256(Path(program['path']).read_bytes()).hexdigest() != program['sha256']:
                    raise ValueError(f'suite ELF changed during execution: {program["name"]}')
                output = run_component([
                    '--component', 'core_elf', '--config', str(config_path),
                    '--test', 'execute', '--elf', program['path'], '--label', program['name'],
                    '--seed', str(seed), '--sim', simulator, '--bender', bender,
                    '--max-cycles', str(max_cycles), '--waves', str(waves),
                    '--reference', reference, '--spike', spike], shared_build=shared_build)
                record['runs'].append({'name': program['name'], 'run': str(output.relative_to(root)), 'status': 'passed'})
            except Exception as error:
                failures.append(program['name'])
                ET.SubElement(case, 'failure', message=str(error)).text = str(error)
                record['runs'].append({'name': program['name'], 'status': 'failed', 'detail': str(error),
                                       'run': str(error.run_dir.relative_to(root)) if hasattr(error, 'run_dir') else None})
            finally:
                case.set('time', str(time.monotonic() - start))
                save()
        for excluded in suite['excluded']:
            case = ET.SubElement(cases, 'testcase', name=excluded['name'])
            ET.SubElement(case, 'skipped', message=excluded['reason'])
        record['status'] = 'failed' if failures else 'passed'
        record['metrics'] = [{'name': 'executed_tests', 'value': len(suite['programs']), 'unit': 'tests'},
                             {'name': 'excluded_tests', 'value': len(suite['excluded']), 'unit': 'tests'}]
    except BaseException:
        record['status'] = 'error'
        raise
    finally:
        record['finished_at'] = datetime.now(timezone.utc).isoformat()
        save()
    print(f'Suite artifacts: {directory}')
    if failures:
        raise RuntimeError(f'{len(failures)} riscv-tests failed: {", ".join(failures)}')
    print(f'PASS: {len(suite["programs"])} riscv-tests; {len(suite["excluded"])} explicitly excluded')
