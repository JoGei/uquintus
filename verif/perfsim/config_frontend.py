"""Shared hardware YAML -> ISA, CorePerfDSL and external-model configuration.

This frontend needs only the project's Python dependencies. Loading/inspecting
a hardware configuration never downloads sources or invokes a model generator.
"""
import json
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'verif/sim/common'))
from hw_config import configuration_label, load_configuration, parameters_for_component
from dependencies import digest
from model import describe, fingerprint, render, render_external_bindings


def resolve_path(name):
    path = Path(name).expanduser()
    if path.is_file():
        return path.resolve()
    if len(path.parts) == 1:
        filename = path.name if path.suffix else path.name+'.yml'
        candidate = ROOT/'config'/filename
        if candidate.is_file():
            return candidate.resolve()
    raise ValueError(f'hardware configuration not found: {name}')


def functional_configuration(config):
    """The pinned ISA plugin is a superset; the execution profile is restricted."""
    return dict(
        isa='rv32'+('e' if config['ISA_E'] else 'i')+('m' if config['ISA_M'] else '')+('c' if config['ISA_C'] else '')+'_zicsr',
        available_privilege_modes=['M', 'U'] if config['ISA_UMODE'] else ['M'],
        execution_mode='M',
        etiss=dict(architecture='RV32IMACFD',
                   misa=0x40000000 | (0x10 if config['ISA_E'] else 0x100) | (config['ISA_M'] << 12) | (config['ISA_C'] << 2) | (config['ISA_UMODE'] << 20),
                   hart_id=config['HART_ID']),
        shared_execution_parameters={k: v for k, v in config.items() if not k.startswith('MUA_')})


def load_configurations(names, imem_latency=1, dmem_latency=1, contract="queue",memory=None):
    if not names or len(set(names)) != len(names):
        raise ValueError('provide distinct hardware configurations')
    catalog_path = ROOT/'config/selectors.json'
    catalog = json.loads(catalog_path.read_text())
    rows = []
    for name in names:
        path = resolve_path(name)
        # Identical complete-schema validation and selectors to RTL builds.
        config = load_configuration(path, catalog)
        model = describe(config, imem_latency, dmem_latency, catalog, contract=contract,memory=memory)
        functional = functional_configuration(config)
        resolved = dict(
            schema_version=1,
            configuration=dict(name=path.stem, path=str(path), file_sha256=digest(path),
                               parameter_sha256=fingerprint(config),
                               label=configuration_label(config), parameters=config),
            rtl_parameters=parameters_for_component(config, config.keys(), catalog),
            functional=functional,
            functional_id=fingerprint(functional),
            coreperfdsl=dict(name=model['name'], id=model['id'], schedule=model['schedule']),
            external_models=model['external_models'],
            environment=dict(imem_response_cycles=imem_latency, dmem_response_cycles=dmem_latency),
            selectors_sha256=digest(catalog_path),
            coverage=model['coverage'], model_status=model['status'],
            approximations=model['approximations'])
        rows.append(dict(path=path, name=path.stem, config=config, model=model, resolved=resolved))
        if contract=='map_dse':resolved['environment']['memory']=model['memory_environment']
    if len({row['name'] for row in rows}) != len(rows):
        raise ValueError('hardware configurations need distinct file stems')
    if len({row['resolved']['functional_id'] for row in rows}) != 1:
        raise ValueError('one ETISS execution requires identical ISA, hart and integration settings')
    return rows


def write_configuration(row, directory):
    """Export the same inputs consumed by generation and execution."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory/'config.yml').write_text(yaml.safe_dump(row['config'], sort_keys=False))
    (directory/'resolved.json').write_text(json.dumps(row['resolved'], indent=2)+'\n')
    (directory/'uqu.corePerfDsl').write_text(render(row['model']))
    (directory/'external_models.inc').write_text(render_external_bindings(row['model']))
    return directory
