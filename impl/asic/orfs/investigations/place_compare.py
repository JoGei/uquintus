#!/usr/bin/env python3
"""Replay the two IHP wire-load experiment netlists through identical ORFS placement."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

import yaml

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
SPEC=importlib.util.spec_from_file_location('uqu_synth',HERE.parent/'common/synth.py')
synth=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(synth)
REL=Path('ihp-sg13g2/uqu_core/base')
STAGES=('floorplan','io','global_place','resize','detail_place','repair_timing')


def write_json(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n')


def summarize(run,modules):
    result={}
    for stage in STAGES:
        counts={}
        lef_area=0.0
        for line in (run/f'snapshots/{stage}.cells.tsv').read_text().splitlines():
            name,count,area=line.split('\t')
            counts[name]=int(count)
            lef_area+=int(count)*float(area)
        # Keep Liberty logic area distinct from physical-only masters.
        logical={n:c for n,c in counts.items() if n in modules}
        metrics={x['name']:x['value'] for x in synth.buffer_metrics(modules,logical)}
        metrics.update(cell_count=sum(counts.values()),lef_cell_area=lef_area,
                       cell_area=sum(c*float(modules[n]['attributes']['area']) for n,c in logical.items()),
                       physical_only_count=sum(c for n,c in counts.items() if n not in modules))
        timing=run/f'snapshots/{stage}.timing.tsv'
        if timing.exists():
            metrics.update({k:float(v) for k,v in (l.split('\t') for l in timing.read_text().splitlines())})
        result[stage]=metrics
    return result


def execute(case,source,directory,flow,openroad,jobs,modules,source_summary,resume):
    run=directory/case
    results=run/'results'/REL
    results.mkdir(parents=True)
    if resume:
        for folder in ('results','reports','logs','snapshots'):
            shutil.copytree(resume/case/folder,run/folder,dirs_exist_ok=True)
    for name in ('1_synth.odb','1_synth.sdc'):
        shutil.copyfile(source/case/'results'/REL/name,results/name)
    shutil.copyfile(source/case/'mapped.v',run/'mapped.v')
    shutil.copyfile(source/case/'constraints.sdc',run/'constraints.sdc')
    abc_script=source/f'{case}.script'
    config=yaml.safe_load((source/case/'config.yml').read_text())
    (run/'config.yml').write_text(yaml.safe_dump(config,sort_keys=False))
    settings=dict(DESIGN_NAME='uqu_core',VERILOG_FILES=str(run/'mapped.v'),
                  SYNTH_NETLIST_FILES=str(run/'mapped.v'),SDC_FILE=str(run/'constraints.sdc'),
                  CLOCK_PERIOD='20',DIE_AREA='0 0 1240 1240',CORE_AREA='20 20 1220 1220',
                  PLACE_DENSITY='0.65',REMOVE_ABC_BUFFERS=synth.BUFFERING_SETTINGS['REMOVE_ABC_BUFFERS'],
                  GPL_TIMING_DRIVEN=synth.BUFFERING_SETTINGS['GPL_TIMING_DRIVEN'],
                  GPL_ROUTABILITY_DRIVEN='1',TNS_END_PERCENT='100',
                  SKIP_REPORT_METRICS='0',REPORT_CLOCK_SKEW='0',IO_CONSTRAINTS=str(HERE/'fixed_pins.tcl'))
    hooks={'floorplan':'FLOORPLAN','io':'IO_PLACEMENT','global_place':'GLOBAL_PLACE',
           'resize':'RESIZE','detail_place':'DETAIL_PLACE','repair_timing':'REPAIR_TIMING_POST_PLACE'}
    for stage,hook in hooks.items():
        path=run/f'{stage}.tcl'
        path.write_text(f'set uqu_snapshot {stage}\nsource {HERE}/place_audit.tcl\n')
        settings[f'POST_{hook}_TCL']=str(path)
    platform=ROOT/'impl/asic/orfs/platforms/ihp-sg13g2/config.mk'
    (run/'config.mk').write_text(f'include {platform}\n'+
        ''.join(f'export {k} = {v}\n' for k,v in settings.items()))
    command=['make','--no-print-directory','-C',str(flow),f'DESIGN_CONFIG={run}/config.mk',
             f'WORK_HOME={run}',f'OPENROAD_EXE={openroad}',f'PYTHON_EXE={sys.executable}',
             f'NUM_CORES={jobs}','-o',str(results/'1_synth.odb'),'-o',str(results/'1_synth.sdc'),
             'place','place_repair_timing']
    if resume:
        # The initial attempt completed resize; only its post-DPL audit failed.
        # Preserve those checkpoints and rerun DPL plus timing repair in a new run.
        command[-2:-2]=['-o',str(results/'3_4_place_resized.odb'),
                        '-o',str(results/'2_floorplan.sdc')]
    inputs=[run/'mapped.v',run/'constraints.sdc',run/'config.mk',results/'1_synth.odb',results/'1_synth.sdc',
            source/'summary.json',abc_script,platform,HERE/'place_compare.py',HERE/'place_audit.tcl',HERE/'fixed_pins.tcl',
            HERE.parent/'common/synth.py',flow/'Makefile',*run.glob('*.tcl')]
    if resume:
        inputs += [results/'3_4_place_resized.odb',results/'2_floorplan.sdc',resume/case/'report.json']
    for folder in (flow/'scripts',flow/'util',flow/'platforms/ihp-sg13g2'):
        inputs.extend(p for p in folder.rglob('*') if p.is_file())
    record=dict(schema_version=1,kind='synthesis',status='running',
        configuration=dict(name='rv32i_zfinx',parameters=config),component='uqu_core',
        target='orfs_ihp-sg13g2',selection=f'place_compare_{case}',started_at=synth.now(),
        command=command,metrics=[],artifacts=[],
        context=dict(stage='placed_pre_cts',experiment='ihp_abc_wireloads',mapping=case,
            clock_period_ns=20,die_area_um=[0,0,1240,1240],core_area_um=[20,20,1220,1220],
            place_density=0.65,remove_abc_buffers=True,placement_timing_driven=True,
            abc_wire_loads=(case=='original'),abc_script=synth.key(abc_script),
            abc_script_sha256=synth.digest(abc_script),parasitics='placement_estimated',
            resumed_after_resize_from=str(resume) if resume else None,
            source_directory=str(source),source_mapping_metrics=source_summary[case],
            openroad=synth.output([str(openroad),'-version']),openroad_sha256=synth.digest(openroad),
            orfs_revision=synth.orfs_revision(flow)),
        input_scope='Source mapped netlist/ODB/SDC, experiment and installed flow/platform inputs',
        input_sha256={synth.key(p):synth.digest(p) for p in dict.fromkeys(inputs)})
    write_json(run/'report.json',record)
    print(f'Starting {case}: {run}',flush=True)
    try:
        with (run/'placement.log').open('w') as log:
            process=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
        if process.returncode:
            raise RuntimeError(f'{case}: ORFS exited {process.returncode}; see {run}/placement.log')
        summary=summarize(run,modules)
        write_json(run/'stages.json',summary)
        final=summary['repair_timing']
        if final['placement_violations']!=0:
            raise ValueError(f'{case}: final placement is illegal')
        units={'cell_count':'cells','cell_area':'um2','lef_cell_area':'um2','buffer_count':'cells',
               'buffer_area':'um2','setup_worst_slack':'ns','setup_total_negative_slack':'ns',
               'hold_worst_slack':'ns','slew_violations':'pins','capacitance_violations':'pins',
               'fanout_violations':'pins','placement_violations':'violations'}
        record.update(status='passed',metrics=[dict(name=k,value=final[k],unit=u) for k,u in units.items()],
            detail='Placement and timing-repair stages completed with legal placement; parasitics are placement estimates, clock is ideal. Timing/electrical violations are reported separately.')
        return summary
    except BaseException as error:
        record.update(status='failed',detail=str(error))
        print(str(error),flush=True)
        raise
    finally:
        record['finished_at']=synth.now()
        record['artifacts']=[str(p.relative_to(run)) for p in run.rglob('*') if p.is_file()
            and p.name!='report.json' and p.suffix in ('.json','.log','.rpt','.tsv','.tcl','.mk','.sdc','.yml')]
        write_json(run/'report.json',record)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=ROOT/'build/investigations/ihp-buffering')
    parser.add_argument('--orfs-root',required=True,type=Path)
    parser.add_argument('--openroad',required=True,type=Path)
    parser.add_argument('--jobs',type=int,default=4)
    parser.add_argument('--resume-from',type=Path,
                        help='Reuse this comparison run through resize, rerunning DPL and timing repair')
    args=parser.parse_args()
    if args.jobs<1: parser.error('--jobs must be positive')
    source=args.source.resolve();flow=synth.flow_directory(str(args.orfs_root))
    source_summary=json.loads((source/'summary.json').read_text())
    for name,expected in source_summary['artifact_sha256'].items():
        if synth.digest(source/name)!=expected: raise ValueError('Changed source experiment artifact: '+name)
    modules=json.loads((source/'original/mapped.json').read_text())['modules']
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory=ROOT/'build/uquintus-rv32i_zfinx/orfs_ihp-sg13g2'/f'place-compare-{stamp}-{uuid.uuid4().hex[:8]}'
    directory.mkdir(parents=True)
    print(f'Comparison: {directory}',flush=True)
    results={};errors=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures={case:pool.submit(execute,case,source,directory,flow,args.openroad.resolve(),args.jobs,modules,source_summary,
                                 args.resume_from.resolve() if args.resume_from else None)
                 for case in ('original','no_wireload')}
        for case,future in futures.items():
            try: results[case]=future.result()
            except Exception as error: errors.append(str(error))
    if errors: raise RuntimeError('\n'.join(errors))
    # Pin locations and floorplan geometry must match, rather than just the input settings.
    for stage in STAGES:
        for kind in ('pins','geometry'):
            data=[sorted((directory/case/f'snapshots/{stage}.{kind}.tsv').read_text().splitlines())
                  for case in ('original','no_wireload')]
            if data[0]!=data[1]: raise ValueError(f'{stage}: unequal {kind} in comparison')
    write_json(directory/'comparison.json',dict(stages=results,identical_geometry_and_pins=True,
        source=str(source),source_summary_sha256=synth.digest(source/'summary.json')))
    print(json.dumps({k:v['repair_timing'] for k,v in results.items()},indent=2),flush=True)


if __name__=='__main__':
    main()
