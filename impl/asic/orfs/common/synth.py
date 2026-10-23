#!/usr/bin/env python3
"""GNU Make helper: external ORFS synthesis and placement with retained evidence."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import uuid

import yaml

ROOT = Path(__file__).resolve().parents[4]
COMMON = Path(__file__).resolve().parent
ORFS = COMMON.parent
TARGETS = ORFS.parent/'targets.yml'
# Flow policy, independent of hardware parameters. Physical settings take effect
# when the generated external-design configuration is used for placement.
BUFFERING_SETTINGS = dict(ABC_AREA='0', REMOVE_ABC_BUFFERS='1', GPL_TIMING_DRIVEN='1')
TIMING_REGIONS = ('IF','DE','EX','MEM','WB','CORE')
TIMING_SCOPES = ('full','reg_to_reg','input_to_reg','reg_to_output','input_to_output')
sys.path.insert(0, str(ROOT/'verif/sim/common'))
from hw_config import load_configuration, parameters_for_component, write_header
from component_runner import bender_include_dirs


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def output(command, cwd=ROOT):
    try:
        return subprocess.check_output(command, cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f'Tool command failed: {command}\n{error.output}') from error


def orfs_revision(flow):
    # An archive/container installation need not carry .git. Do not attribute
    # a vendored installation to an unrelated ancestor repository either.
    try:
        top=Path(output(['git','rev-parse','--show-toplevel'],flow)).resolve()
        return output(['git','rev-parse','HEAD'],flow) if top==flow.parent else None
    except RuntimeError:
        return None


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def key(path):
    path=path.resolve()
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def make_path(path):
    value=str(path)
    if any(c in value for c in ' \t\n\r$#\\'):
        raise ValueError(f'ORFS file paths must not contain whitespace or Make metacharacters: {value}')
    return value


def flow_directory(root):
    if root:
        flow=Path(root).expanduser().resolve()/'flow'
    else:
        launcher=shutil.which('orfs')
        if not launcher:
            raise ValueError('Supply ORFS_ROOT (containing flow/Makefile), or orfs --flow-dir on PATH')
        flow=Path(output([launcher,'--flow-dir'])).resolve()
    if not (flow/'Makefile').is_file():
        raise ValueError(f'ORFS flow/Makefile not found: {flow}')
    return flow


def executable(explicit, name, fallback):
    candidate=explicit or shutil.which(name) or str(fallback)
    found=shutil.which(candidate)
    if not found:
        raise ValueError(f'{name} executable not found; supply {name.upper()}_EXE or PATH')
    return Path(found).resolve()


def abc_wire_load_policy(script):
    """Qualify the installed speed script rather than copy or patch ORFS."""
    commands=[shlex.split(line,comments=True) for line in script.read_text().splitlines()]
    for name in ('buffer','stime','upsize','dnsize'):
        matches=[tokens for tokens in commands if tokens and tokens[0]==name]
        if matches!=[[name,'-c']]:
            raise ValueError(f'Baseline requires exactly one "{name} -c" in {script}; '
                             'qualify this ORFS script before changing the wire-load policy')
    return dict(abc_script=key(script),abc_script_sha256=digest(script),abc_wire_loads=True)


def resolved_buffering_settings(text):
    settings={}
    for name,expected in BUFFERING_SETTINGS.items():
        values=[line.partition(': ')[2].strip() for line in text.splitlines()
                if line.startswith(name+': ')]
        if values!=[expected]:
            raise ValueError(f'ORFS buffering policy requires {name}={expected}; resolved {values}')
        settings[name]=values[0]
    return settings


def check_abc_execution(log,script,expected_hash):
    commands=[shlex.split(line) for line in log.read_text().splitlines()
              if line.startswith(('abc ','abc_new '))]
    if not commands or any(tokens[:3]!=['abc','-script',str(script)] for tokens in commands):
        raise ValueError('Yosys did not execute the qualified ORFS ABC speed script; see '+str(log))
    if digest(script)!=expected_hash:
        raise ValueError('ABC speed script changed during synthesis: '+str(script))


def reset_input_constraints(delay):
    if delay is None:
        return ''
    if not math.isfinite(delay) or delay<0:
        raise ValueError('reset maximum input delay must be finite and nonnegative')
    return f'''# Integration reset arrival window: earliest 0 ns, latest {delay:g} ns.
set_input_delay -min 0 -clock core_clk [get_ports rst_ni]
set_input_delay -max {delay:g} -clock core_clk [get_ports rst_ni]
'''


def sdc(period,reset_input_delay=None):
    if not math.isfinite(period) or period <= 0:
        raise ValueError('clock period must be finite and positive')
    reset_constraints=reset_input_constraints(reset_input_delay)
    return f'''# Exploratory mapped-netlist constraints; no extracted wire parasitics.
set_units -time ns -capacitance pF
create_clock -name core_clk -period {period:g} [get_ports clk_i]
set data_inputs [all_inputs -no_clocks]
set_input_delay {period*0.2:g} -clock core_clk $data_inputs
{reset_constraints}set_output_delay {period*0.2:g} -clock core_clk [all_outputs]
set_input_transition 0.1 $data_inputs
set_load 0.01 [all_outputs]
set_clock_uncertainty 0.1 [get_clocks core_clk]
'''


def constraint_profile(period,reset_input_delay,supplied):
    if not math.isfinite(period) or period<=0:
        raise ValueError('clock period must be finite and positive')
    if supplied:
        if reset_input_delay is not None:
            raise ValueError('SDC and RESET_INPUT_DELAY_NS cannot be combined; put reset timing in the supplied SDC')
        source=Path(supplied).expanduser().resolve()
        text=source.read_text()
        if not text.strip(): raise ValueError('Supplied SDC is empty: '+str(source))
        return text,source,dict(constraint_profile='integration',sdc_source=key(source),sdc_sha256=digest(source))
    return sdc(period,reset_input_delay),None,dict(constraint_profile='standalone',
        io_delay_fraction=0.2,input_transition_ns=0.1,output_load_pf=0.01,clock_uncertainty_ns=0.1,
        reset_input_max_delay_ns=reset_input_delay if reset_input_delay is not None else period*0.2,
        reset_input_min_delay_ns=0 if reset_input_delay is not None else period*0.2)


def implementation_settings(die_text,core_text,density):
    def box(text,name):
        values=[float(v) for v in text.split()]
        if len(values)!=4 or not all(math.isfinite(v) for v in values) or values[0]>=values[2] or values[1]>=values[3]:
            raise ValueError(name+' requires finite x0 y0 x1 y1 coordinates with positive dimensions')
        return values
    die=box(die_text,'DIE_AREA');core=box(core_text,'CORE_AREA')
    if core[0]<die[0] or core[1]<die[1] or core[2]>die[2] or core[3]>die[3]:
        raise ValueError('CORE_AREA must be inside DIE_AREA')
    if not math.isfinite(density) or not 0<density<1:
        raise ValueError('PLACE_DENSITY must be finite and between 0 and 1')
    settings=dict(DIE_AREA=' '.join(f'{v:g}' for v in die),CORE_AREA=' '.join(f'{v:g}' for v in core),
                  PLACE_DENSITY=f'{density:g}',GPL_ROUTABILITY_DRIVEN='1',TNS_END_PERCENT='100',
                  SKIP_REPORT_METRICS='0',REPORT_CLOCK_SKEW='0',
                  POST_REPAIR_TIMING_POST_PLACE_TCL=make_path(COMMON/'place_metrics.tcl'))
    context=dict(die_area_um=die,core_area_um=core,place_density=density,
                 placement_routability_driven=True,tns_end_percent=100,pin_placement='ORFS automatic')
    return settings,context


def timing_summary(directory,stage,expected_period):
    folder=directory/'timing'/stage
    values={}
    for line in (folder/'metrics.tsv').read_text().splitlines():
        name,value=line.split('\t')
        if name in values: raise ValueError('Duplicate timing metric: '+name)
        values[name]=float(value)
    required=('clock_period_ns','minimum_clock_period','estimated_fmax','setup_worst_slack',
              'hold_worst_slack','setup_total_negative_slack','slew_violations',
              'capacitance_violations','fanout_violations')
    if any(k not in values or not math.isfinite(values[k]) for k in required):
        raise ValueError('Missing/nonfinite timing evidence: '+str(folder))
    if values['minimum_clock_period']<=0 or values['estimated_fmax']<=0 or not math.isclose(
            values['estimated_fmax'],1000/values['minimum_clock_period'],rel_tol=1e-6):
        raise ValueError('Timing period/frequency evidence disagrees')
    if not math.isclose(values['clock_period_ns'],expected_period,rel_tol=1e-5):
        raise ValueError('SDC clock period must match CLOCK_PERIOD_NS / --clock-period')
    regions=dict(status='not_recorded')
    allowed=set(TIMING_SCOPES)
    if (folder/'regions.tsv').is_file():
        rows=[line.split('\t') for line in (folder/'regions.tsv').read_text().splitlines()]
        if not rows or rows[0] not in (['status','available'],['status','not_applicable']):
            raise ValueError('Invalid stage register-region status')
        regions=dict(status=rows[0][1])
        if regions['status']=='available':
            counts={}
            for fields in rows[1:]:
                if len(fields)!=2 or fields[0] not in TIMING_REGIONS or fields[0] in counts:
                    raise ValueError('Invalid/duplicate stage register region')
                counts[fields[0]]=int(fields[1])
            if set(counts)!=set(TIMING_REGIONS) or min(counts.values())<0 or not sum(counts.values()):
                raise ValueError('Incomplete/empty stage register inventory')
            inventory={};observed=dict.fromkeys(TIMING_REGIONS,0)
            for line in (folder/'register_regions.tsv').read_text().splitlines():
                fields=line.split('\t')
                if len(fields)!=3 or fields[0] not in counts or not fields[1] or fields[1] in inventory:
                    raise ValueError('Invalid/duplicate stage register inventory entry')
                inventory[fields[1]]=fields[0];observed[fields[0]]+=1
            if observed!=counts: raise ValueError('Stage register counts disagree with inventory')
            regions.update(register_cells=counts,policy='receiving_stage_inputs_and_local_state_v1',
                           inventory='register_regions.tsv',shared_region='CORE: shared, unmatched or mixed aliases')
            allowed.update('stage_'+r for r in TIMING_REGIONS)
            allowed.update('stage_'+a+'_to_'+b for a in TIMING_REGIONS for b in TIMING_REGIONS)
        elif len(rows)!=1:
            raise ValueError('Non-core stage report must not claim register regions')
    paths={}
    for line in (folder/'paths.tsv').read_text().splitlines():
        fields=line.split('\t');scope,delay=fields[:2]
        if scope not in allowed or delay not in ('max','min'):
            raise ValueError('Unknown timing path scope: '+line)
        label=scope+'_'+delay
        if label in paths: raise ValueError('Duplicate timing path scope: '+label)
        if fields[2:]==['no_paths']:
            paths[label]=dict(status='no_paths')
        elif len(fields)==5 and math.isfinite(float(fields[2])) and fields[3] and fields[4]:
            paths[label]=dict(status='timed',slack_ns=float(fields[2]),startpoint=fields[3],endpoint=fields[4])
        else: raise ValueError('Invalid timing path evidence: '+line)
    expected={scope+'_'+delay for scope in allowed for delay in ('max','min')}
    if set(paths)!=expected or paths['full_max']['status']!='timed' or paths['full_min']['status']!='timed':
        raise ValueError('Incomplete constrained-path evidence')
    for delay,metric in (('max','setup_worst_slack'),('min','hold_worst_slack')):
        if not math.isclose(paths['full_'+delay]['slack_ns'],values[metric],abs_tol=1e-4):
            raise ValueError('Full path and global worst slack disagree')
    summary=dict(stage=stage,clock=(folder/'clock.txt').read_text().strip(),metrics=values,paths=paths,regions=regions)
    (folder/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return summary


def scoped_timing_metrics(summary):
    scopes=(*TIMING_SCOPES[1:],*('stage_'+r for r in TIMING_REGIONS))
    return [dict(name=scope+'_'+label+'_worst_slack',value=path['slack_ns'],unit='ns')
            for scope in scopes for delay,label in (('max','setup'),('min','hold'))
            if (path:=summary['paths'].get(scope+'_'+delay,{})).get('status')=='timed']


def placed_metrics(directory,modules):
    folder=directory/'physical'
    if (folder/'placement_violations.txt').read_text().strip()!='0':
        raise ValueError('Placement did not pass legality checking')
    counts={};lef_area=0.0
    for line in (folder/'cells.tsv').read_text().splitlines():
        name,count,area=line.split('\t');count=int(count);area=float(area)
        if name in counts or count<=0 or not math.isfinite(area) or area<0:
            raise ValueError('Invalid physical cell evidence: '+line)
        counts[name]=count;lef_area+=count*area
    if not counts: raise ValueError('Empty physical design')
    logical={n:c for n,c in counts.items() if n in modules}
    area=sum(c*float(modules[n]['attributes']['area']) for n,c in logical.items())
    if not math.isfinite(area) or area<=0: raise ValueError('Invalid physical Liberty cell area')
    metrics=[dict(name='cell_count',value=sum(counts.values()),unit='cells'),
             dict(name='cell_area',value=area,unit='um2'),dict(name='lef_cell_area',value=lef_area,unit='um2'),
             dict(name='physical_only_count',value=sum(c for n,c in counts.items() if n not in modules),unit='cells'),
             dict(name='placement_violations',value=0,unit='violations'),*buffer_metrics(modules,logical)]
    (folder/'cells.json').write_text(json.dumps(counts,indent=2)+'\n')
    return metrics


def buffer_metrics(modules, counts):
    # read_liberty represents a non-inverting buffer by connecting its input
    # and output ports to the same bit. This also counts clock buffers without
    # depending on a particular foundry's cell names.
    count=0
    area=0.0
    for name,instances in counts.items():
        module=modules[name]
        ports=list(module.get('ports',{}).values())
        if len(ports)!=2 or sorted(p['direction'] for p in ports)!=['input','output']:
            continue
        bits=ports[0]['bits']
        if len(bits)!=1 or type(bits[0]) is not int or bits!=ports[1]['bits']:
            continue
        cell_area=float(module['attributes'].get('area','nan'))
        if not math.isfinite(cell_area) or cell_area<=0:
            raise ValueError('Missing/invalid buffer cell area: '+name)
        count+=instances
        area+=instances*cell_area
    return [dict(name='buffer_count',value=count,unit='cells'),
            dict(name='buffer_area',value=area,unit='um2')]


def mapped_metrics(stat_path, netlist_path, top):
    stats=json.loads(stat_path.read_text())
    design=stats['design']
    modules=json.loads(netlist_path.read_text())['modules']
    module=modules[top]
    counts={}
    for cell in module['cells'].values():
        name=cell['type']
        if name.startswith('$') or 'liberty_cell' not in modules.get(name,{}).get('attributes',{}):
            raise ValueError('Unmapped or non-library synthesis cell: '+name)
        counts[name]=counts.get(name,0)+1
    total=sum(counts.values())
    if not total or total != design['num_cells']:
        raise ValueError('Mapped netlist and synthesis statistics disagree or are empty')
    area=design['area']
    if not math.isfinite(area) or area<=0:
        raise ValueError('Missing/invalid mapped cell area')
    return [dict(name='cell_count',value=total,unit='cells'),
            dict(name='cell_area',value=area,unit='um2'),
            *buffer_metrics(modules,counts)],counts


def timing_metrics(path):
    raw=json.loads(path.read_text())
    fields=(('synth__timing__setup__ws','setup_worst_slack','ns',1),
            ('synth__timing__setup__tns','setup_total_negative_slack','ns',1),
            ('synth__timing__fmax','estimated_fmax','MHz',1e-6))
    result=[]
    for field,name,unit,scale in fields:
        value=raw.get(field)
        if type(value) not in (float,int) or not math.isfinite(value):
            raise ValueError('Missing/nonfinite preplacement timing metric: '+field)
        result.append(dict(name=name,value=value*scale,unit=unit))
    if result[-1]['value']<=0: raise ValueError('No timed clock path')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--action',choices=('synth','impl'),default='synth')
    parser.add_argument('--config',default='rv32i')
    parser.add_argument('--top',choices=('core','fpu'),default='core')
    parser.add_argument('--platform',choices=('sky130hd','ihp-sg13g2'),default='sky130hd')
    parser.add_argument('--clock-period',type=float,default=20)
    parser.add_argument('--reset-input-delay',type=float,default=None,
                        help='Reset maximum input delay in ns; minimum becomes 0 ns (default: legacy data-input budget)')
    parser.add_argument('--jobs',type=int,default=4)
    parser.add_argument('--sdc',default='',help='Integration SDC, used in place of the generated standalone profile')
    parser.add_argument('--die-area',default='0 0 1240 1240')
    parser.add_argument('--core-area',default='20 20 1220 1220')
    parser.add_argument('--place-density',type=float,default=0.65)
    parser.add_argument('--bender',default='bender')
    parser.add_argument('--orfs-root',default=os.environ.get('ORFS_ROOT',''))
    parser.add_argument('--yosys',default=os.environ.get('YOSYS_EXE',''))
    parser.add_argument('--openroad',default=os.environ.get('OPENROAD_EXE',''))
    args=parser.parse_args()
    constraints,supplied_sdc,constraint_context=constraint_profile(args.clock_period,args.reset_input_delay,args.sdc)
    physical_settings,physical_context=implementation_settings(args.die_area,args.core_area,args.place_density)
    if args.jobs<1: raise ValueError('jobs must be positive')
    config_path=Path(args.config)
    if not config_path.is_file(): config_path=ROOT/'config'/f'{args.config}.yml'
    catalog=json.loads((ROOT/'config/selectors.json').read_text())
    config=load_configuration(config_path,catalog)
    manifest=yaml.safe_load(TARGETS.read_text())[args.top]
    parameters=parameters_for_component(config,config.keys() if manifest['parameters']=='all'
                                        else manifest['parameters'],catalog)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory=ROOT/'build'/f'uquintus-{config_path.stem}'/f'orfs_{args.platform}'/f'{args.action}-{args.top}-{stamp}-{uuid.uuid4().hex[:8]}'
    directory.mkdir(parents=True)
    record=dict(schema_version=1,kind='synthesis',status='running',
                configuration=dict(name=config_path.stem,parameters=config),component=manifest['module'],
                target=f'orfs_{args.platform}',selection=args.action,started_at=now(),
                input_scope='RTL, recursive include headers, Bender lock, constraints, project/ORFS scripts and platform inputs',
                context=dict(platform=args.platform,clock_period_ns=args.clock_period,
                             stage='mapped_preplacement',**constraint_context,
                             sta_interconnect='ideal_preplacement',abc_wire_loads=True,
                             remove_abc_buffers=True,placement_timing_driven=True,
                             placement_parasitics='placement_estimated'),
                input_sha256={},metrics=[],artifacts=[])
    if args.action=='impl': record['context'].update(physical_context)
    metadata=directory/'report.json'
    metadata.write_text(json.dumps(record,indent=2)+'\n')
    print('Artifacts: '+str(directory),flush=True)
    try:
        if config['DEBUG']: raise ValueError('Core debug is not implemented')
        if args.top=='fpu' and not config['ISA_ZFINX']:
            raise ValueError('FPU synthesis requires ISA_ZFINX=1; disabled FPU is intentionally empty')
        flow=flow_directory(args.orfs_root)
        abc_script=flow/'scripts/abc_speed.script'
        record['context'].update(abc_wire_load_policy(abc_script))
        shutil.copyfile(abc_script,directory/'abc_speed.script')
        yosys=executable(args.yosys,'yosys',flow.parent/'tools/install/yosys/bin/yosys')
        openroad=executable(args.openroad,'openroad',flow.parent/'tools/install/OpenROAD/bin/openroad')
        tools=dict(yosys=output([str(yosys),'-V']),yosys_sha256=digest(yosys),
                   openroad=output([str(openroad),'-version']),openroad_sha256=digest(openroad),
                   bender=output([args.bender,'--version']),
                   orfs_revision=orfs_revision(flow))
        tools.update(python=sys.version,python_executable=sys.executable,pyyaml=yaml.__version__)
        abc=yosys.parent/'yosys-abc'
        if not abc.is_file(): raise ValueError('Matching yosys-abc executable missing beside Yosys')
        tools.update(abc_sha256=digest(abc))
        revision=output(['git','rev-parse','HEAD'])
        record['revision']=dict(commit=revision,dirty=bool(output(['git','status','--porcelain'])))
        frontend='slang' if config['ISA_ZFINX'] else ''
        record['context'].update(frontend=frontend or 'verilog',tools=tools)
        if frontend:
            probe=output([str(yosys),'-Q','-T','-p','plugin -i slang; help read_slang'])
            (directory/'frontend.log').write_text(probe+'\n')
            search=[Path(p) for p in os.environ.get('YOSYS_PLUGIN_PATH','').split(os.pathsep) if p]
            search += [yosys.parent.parent/'share/yosys/plugins']
            plugin=next((p/'slang.so' for p in search if (p/'slang.so').is_file()),None)
            if plugin is None: raise ValueError('Cannot identify loaded Slang binary for provenance')
            tools.update(slang_plugin=str(plugin.resolve()),slang_sha256=digest(plugin))
        options=['-t',manifest['bender_target'],'-t','synthesis','-t','tech_cells_generic_exclude_deprecated']
        if not config['ISA_ZFINX']: options += ['--no-deps']
        listing=output([args.bender,'script','flist',*options])
        sources=[Path(line).resolve() for line in listing.splitlines() if line.strip()]
        if not sources or any(not p.is_file() or p.suffix not in ('.v','.sv') for p in sources):
            raise ValueError('Bender must return existing synthesizable Verilog/SystemVerilog files')
        if any(p.is_relative_to(ROOT/'verif') for p in sources):
            raise ValueError('Verification source selected for synthesis')
        tree=json.loads(output([args.bender,'sources',*options]))
        includes=[directory/'include',*bender_include_dirs(tree)]
        write_header(catalog,includes[0])
        (directory/'sources.f').write_text('\n'.join(str(p) for p in sources)+'\n')
        (directory/'config.yml').write_text(yaml.safe_dump(config,sort_keys=False))
        (directory/'parameters.json').write_text(json.dumps(parameters,indent=2)+'\n')
        (directory/'bender_sources.json').write_text(json.dumps(tree,indent=2)+'\n')
        shutil.copyfile(ROOT/'Bender.lock',directory/'Bender.lock')
        if supplied_sdc: shutil.copyfile(supplied_sdc,directory/'constraints.sdc')
        else: (directory/'constraints.sdc').write_text(constraints)
        platform=ORFS/'platforms'/args.platform/'config.mk'
        settings=dict(DESIGN_NAME=manifest['module'],VERILOG_FILES=' '.join(map(make_path,sources)),
                      VERILOG_INCLUDE_DIRS=' '.join(map(make_path,includes)),
                      VERILOG_TOP_PARAMS=' '.join(f'{k} {v}' for k,v in parameters.items()),
                      SDC_FILE=make_path(supplied_sdc or directory/'constraints.sdc'),CLOCK_PERIOD=f'{args.clock_period:g}',
                      ABC_CLOCK_PERIOD_IN_PS=f'{args.clock_period*1000:g}',
                      **BUFFERING_SETTINGS,
                      SYNTH_HDL_FRONTEND=frontend,SYNTH_HIERARCHICAL='0',
                      SYNTH_CANONICALIZE_TCL=make_path(COMMON/'canonicalize.tcl'),
                      SYNTH_SCRIPT=make_path(COMMON/'synth.tcl'),
                      POST_SYNTH_TCL=make_path(COMMON/'metrics.tcl'),
                      UQU_ALLOW_LATCHES=str(int(args.top=='core' and config['MUA_REGFILE_IMPL']=='latch')))
        if args.action=='impl': settings.update(physical_settings)
        (directory/'config.mk').write_text('include '+make_path(platform)+'\n'+
            '\n'.join(f'export {k} = {v}' for k,v in settings.items())+'\n')
        # Hash all potentially consumed includes and flow/platform resources,
        # including library contents, rather than only a mutable installation path.
        inputs=[*sources,config_path,ROOT/'Makefile',ROOT/'Bender.yml',ROOT/'Bender.lock',ROOT/'config/selectors.json',
                ROOT/'verif/sim/common/hw_config.py',ROOT/'verif/sim/common/component_runner.py',platform,
                *(COMMON.glob('*.py')),*(COMMON.glob('*.tcl')),TARGETS]
        if supplied_sdc: inputs.append(supplied_sdc)
        inputs.append(directory/'constraints.sdc')
        for folder in includes:
            inputs += [p for p in folder.rglob('*') if p.suffix in ('.vh','.svh')]
        for folder in (flow/'scripts',flow/'util',flow/'platforms'/args.platform):
            inputs += [p for p in folder.rglob('*') if p.is_file()]
        inputs += [flow/'Makefile']
        record['input_sha256']={key(p):digest(p) for p in dict.fromkeys(inputs)}
        library_hashes={key(p):digest(p) for p in (flow/'platforms'/args.platform/'lib').glob('*.lib')}
        record['context']['library_sha256']=library_hashes
        command=['make','--no-print-directory','-C',str(flow),f'DESIGN_CONFIG={directory}/config.mk',
                 f'WORK_HOME={directory}',f'YOSYS_EXE={yosys}',f'OPENROAD_EXE={openroad}',
                 f'PYTHON_EXE={sys.executable}',f'NUM_CORES={args.jobs}','synth']
        libraries=output([*command[:-1],'print-LIB_FILES',
                          *(f'print-{name}' for name in BUFFERING_SETTINGS)])
        record['context']['orfs_buffering_settings']=resolved_buffering_settings(libraries)
        resolved=next((line.partition(': ')[2] for line in libraries.splitlines() if line.startswith('LIB_FILES: ')),None)
        if not resolved: raise ValueError('ORFS did not resolve its synthesis libraries')
        record['context']['mapping_libraries']={str(Path(p).resolve()):digest(Path(p)) for p in resolved.split()}
        record['command']=command
        metadata.write_text(json.dumps(record,indent=2)+'\n')
        with (directory/'synthesis.log').open('w') as log:
            process=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        if process.returncode:
            raise RuntimeError(f'ORFS failed ({process.returncode}); see {directory}/synthesis.log')
        reports=directory/'reports'/args.platform/manifest['module']/'base'
        results=directory/'results'/args.platform/manifest['module']/'base'
        check_abc_execution(directory/'logs'/args.platform/manifest['module']/'base/1_2_yosys.log',
                            abc_script,record['context']['abc_script_sha256'])
        if not (results/'1_synth.odb').is_file(): raise ValueError('ORFS synthesis database missing')
        metrics,counts=mapped_metrics(reports/'uqu_stat.json',results/'uqu_mapped.json',manifest['module'])
        metrics += timing_metrics(directory/'logs'/args.platform/manifest['module']/'base/1_synth.json')
        summary=timing_summary(directory,'mapped_preplacement',args.clock_period)
        record['timing_paths']=summary['paths']
        record['timing_regions']=summary['regions']
        metrics += scoped_timing_metrics(summary)
        (directory/'cells.json').write_text(json.dumps(counts,indent=2)+'\n')
        (directory/'mapped_metrics.json').write_text(json.dumps(metrics,indent=2)+'\n')
        if args.action=='impl':
            record['synthesis_command']=command
            command=[*command[:-1],'place','place_repair_timing']
            record.update(command=command,detail='Mapped synthesis complete; physical implementation running')
            metadata.write_text(json.dumps(record,indent=2)+'\n')
            with (directory/'implementation.log').open('w') as log:
                process=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
            if process.returncode:
                raise RuntimeError(f'ORFS implementation failed ({process.returncode}); see {directory}/implementation.log')
            if not (results/'3_6_place_repair_timing.odb').is_file():
                raise ValueError('Post-placement timing-repair database missing')
            summary=timing_summary(directory,'placed_pre_cts',args.clock_period)
            record['timing_paths']=summary['paths']
            record['timing_regions']=summary['regions']
            modules=json.loads((results/'uqu_mapped.json').read_text())['modules']
            metrics=placed_metrics(directory,modules)
            units=dict(minimum_clock_period='ns',estimated_fmax='MHz',setup_worst_slack='ns',
                       hold_worst_slack='ns',setup_total_negative_slack='ns',slew_violations='pins',
                       capacitance_violations='pins',fanout_violations='pins')
            metrics += [dict(name=k,value=summary['metrics'][k],unit=u) for k,u in units.items()]
            metrics += scoped_timing_metrics(summary)
            record['context'].update(stage='placed_pre_cts',sta_interconnect='placement_estimated',clock_model='ideal')
            record['metrics']=metrics
            checks=summary['metrics']
            if checks['setup_worst_slack']<0 or checks['hold_worst_slack']<0 or any(
                    checks[k]!=0 for k in ('slew_violations','capacitance_violations','fanout_violations')):
                raise ValueError('Placement completed but setup/hold or electrical checks failed; inspect timing reports')
        record.update(status='passed',metrics=metrics,
                      detail=('Placement, timing repair, legality, setup/hold and electrical checks passed; '
                              'ideal clock, placement-estimated RC, before CTS and routing.' if args.action=='impl' else
                              'Mapped synthesis and structural checks passed; timing is a preplacement estimate, not physical signoff.'))
    except BaseException as error:
        record.update(status='failed',detail=str(error))
        raise
    finally:
        record['finished_at']=now()
        record['artifacts']=[str(p.relative_to(directory)) for p in directory.rglob('*')
                             if p.is_file() and p!=metadata and p.suffix in
                             ('.json','.log','.tcl','.mk','.sdc','.v','.txt','.rpt','.f','.yml','.lock','.script','.tsv','.def','.odb')]
        metadata.write_text(json.dumps(record,indent=2)+'\n')
    print('PASS: '+args.action+' '+config_path.stem+' '+args.top+' '+args.platform)


if __name__=='__main__':
    try:
        main()
    except (ValueError,OSError,RuntimeError,subprocess.SubprocessError,yaml.YAMLError) as error:
        sys.exit(str(error))
