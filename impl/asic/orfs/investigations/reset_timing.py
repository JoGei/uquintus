#!/usr/bin/env python3
"""Compare 4 ns and 1 ns reset arrival on the same saved IHP placements."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import importlib.util
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
SPEC=importlib.util.spec_from_file_location('uqu_synth',HERE.parent/'common/synth.py')
synth=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(synth)
REL=Path('ihp-sg13g2/uqu_core/base')
UNITS=dict(minimum_clock_period='ns',estimated_fmax='MHz',setup_worst_slack='ns',
           hold_worst_slack='ns',setup_total_negative_slack='ns',slew_violations='pins',
           capacitance_violations='pins',fanout_violations='pins',placement_violations='violations')


def write_json(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n')


def metrics(path):
    values={k:float(v) for k,v in (line.split('\t') for line in path.read_text().splitlines())}
    for name in UNITS:
        if name not in values or not math.isfinite(values[name]):
            raise ValueError('Missing/nonfinite timing trial metric: '+name)
    if values['minimum_clock_period']<=0 or values['estimated_fmax']<=0:
        raise ValueError('No timed clock paths')
    if not math.isclose(values['estimated_fmax'],1000/values['minimum_clock_period'],rel_tol=1e-6):
        raise ValueError('Minimum period and frequency disagree')
    return values


def trial(mapping,delay,source,directory,flow,openroad):
    run=directory/f'{mapping}_reset{delay:g}ns'
    run.mkdir()
    parent=json.loads((source/mapping/'report.json').read_text())
    if parent['status']!='passed': raise ValueError('Source placement did not pass')
    results=source/mapping/'results'/REL
    database=results/'3_6_place_repair_timing.odb'
    source_sdc=results/'3_place.sdc'
    constraint_text=source_sdc.read_text()+ '\n'+synth.reset_input_constraints(delay)
    (run/'constraints.sdc').write_text(constraint_text)
    shutil.copyfile(source/mapping/'config.yml',run/'config.yml')
    platform=flow/'platforms/ihp-sg13g2'
    liberty=platform/'lib/sg13g2_stdcell_typ_1p20V_25C.lib'
    rc=platform/'setRC.tcl'
    variables=dict(uqu_liberty=liberty,uqu_database=database,uqu_constraints=run/'constraints.sdc',
                   uqu_rc=rc,uqu_metrics=run/'metrics.tsv')
    (run/'inputs.tcl').write_text(''.join(f'set {k} {{{v}}}\n' for k,v in variables.items()))
    shutil.copyfile(HERE/'reset_timing.tcl',run/'reset_timing.tcl')
    command=[str(openroad),'-no_init','-exit',str(run/'reset_timing.tcl')]
    inputs=[HERE/'reset_timing.py',HERE/'reset_timing.tcl',HERE.parent/'common/synth.py',
            source/mapping/'report.json',source_sdc,database,liberty,rc,
            run/'inputs.tcl',run/'constraints.sdc',run/'config.yml']
    record=dict(schema_version=1,kind='synthesis',status='running',
        configuration=parent['configuration'],component='uqu_core',target='orfs_ihp-sg13g2',
        selection=f'reset_timing_{mapping}_{delay:g}ns',started_at=synth.now(),command=command,
        context=dict(stage='placed_timing_reanalysis',experiment='reset_arrival',mapping=mapping,
            clock_period_ns=20,reset_input_max_delay_ns=delay,reset_input_min_delay_ns=0,
            other_input_output_delay_ns=4,timing_scope='full_interface',
            placement_unchanged=True,source_placement=str(source/mapping),
            parasitics='placement_estimated',clock_model='ideal',
            openroad=synth.output([str(openroad),'-version']),openroad_sha256=synth.digest(openroad),
            orfs_revision=synth.orfs_revision(flow),library_corner='typ_1p20V_25C'),
        input_scope='Unchanged placed ODB, source/new SDC, Liberty/RC, analysis scripts and source-run metadata',
        input_sha256={synth.key(p):synth.digest(p) for p in inputs},metrics=[],artifacts=[])
    write_json(run/'report.json',record)
    print(f'Starting {mapping}, reset 0..{delay:g} ns: {run}',flush=True)
    try:
        with (run/'timing.log').open('w') as log:
            result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
        if result.returncode: raise RuntimeError(f'OpenROAD failed; see {run}/timing.log')
        values=metrics(run/'metrics.tsv')
        write_json(run/'metrics.json',values)
        passed=(values['setup_worst_slack']>=0 and values['hold_worst_slack']>=0 and
                all(values[k]==0 for k in ('slew_violations','capacitance_violations','fanout_violations','placement_violations')))
        record.update(status='passed' if passed else 'failed',
            metrics=[dict(name=k,value=values[k],unit=u) for k,u in UNITS.items()],
            detail='Saved placement reanalyzed with explicit reset min/max arrivals. Cells and placement unchanged; ideal clock and placement-estimated RC. Passing requires setup/hold and electrical/placement checks.')
        return values
    except BaseException as error:
        record.update(status='error',detail=str(error))
        raise
    finally:
        record['finished_at']=synth.now()
        record['artifacts']=[p.name for p in run.iterdir() if p.is_file() and p.name!='report.json']
        write_json(run/'report.json',record)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--orfs-root',required=True,type=Path)
    parser.add_argument('--openroad',required=True,type=Path)
    args=parser.parse_args()
    source=args.source.resolve();flow=synth.flow_directory(str(args.orfs_root))
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory=ROOT/'build/uquintus-rv32i_zfinx/orfs_ihp-sg13g2'/f'reset-timing-{stamp}-{uuid.uuid4().hex[:8]}'
    directory.mkdir(parents=True)
    print('Artifacts: '+str(directory),flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures={f'{mapping}_reset{delay:g}ns':pool.submit(trial,mapping,delay,source,directory,flow,args.openroad.resolve())
                 for mapping in ('original','no_wireload') for delay in (4,1)}
        results={name:future.result() for name,future in futures.items()}
    write_json(directory/'comparison.json',results)
    print(json.dumps(results,indent=2),flush=True)


if __name__=='__main__':
    main()
