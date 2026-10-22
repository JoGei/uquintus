"""Retirement-scoped BPU statistics, validation and common report metrics."""
from pathlib import Path
import re

CATALOG = Path(__file__).resolve().parents[2] / 'common/uqu_bpu_counter_list.vh'
COUNTERS = tuple(name.lower() for name in re.findall(
    r'^`UQU_BPU_COUNTER\(([A-Z_]+)\)$', CATALOG.read_text(), re.M))
if not COUNTERS or len(set(COUNTERS)) != len(COUNTERS):
    raise ValueError('invalid BPU counter catalog')
# Population semantics are unchanged; schema 2 appends replay provenance.
LEGACY_COUNTERS = COUNTERS[:20]
SCOPE = 'retired-window-v1'
DEFINITION = ('Instructions retiring in (start, stop]; lookup metadata sampled on first IF presentation, '
              'outcomes on accepted DE transfer; flushed/faulting instructions excluded')


def unpack_snapshot(packed):
    if type(packed) is not int or not 0 <= packed < 1 << (64*len(COUNTERS)):
        raise ValueError('invalid packed BPU snapshot')
    return [(packed >> (64*n)) & ((1 << 64)-1) for n in range(len(COUNTERS))]


def statistics(start, stop, parameters, retired):
    """Validate post-edge cumulative snapshots and derive the workload delta."""
    names = LEGACY_COUNTERS if isinstance(start, (list, tuple)) and len(start) == 20 else COUNTERS
    snapshots = []
    for values in (start, stop):
        if not isinstance(values, (list, tuple)) or len(values) != len(names) or any(
                type(v) is not int or not 0 <= v < 2**64 for v in values):
            raise ValueError('invalid BPU snapshot counter values')
        snapshots.append(dict(zip(names, values)))
    begin, end = snapshots
    counts = {name:end[name]-begin[name] for name in names}
    if any(value < 0 for value in counts.values()):
        raise ValueError('BPU counters decreased inside workload window')
    if type(retired) is not int or retired <= 0 or counts['retired_instructions'] != retired:
        raise ValueError('BPU retirement count differs from benchmark window')
    try:
        mode = {0:'none', 1:'static_not_taken', 2:'bimodal', 'none':'none',
                'static_not_taken':'static_not_taken', 'bimodal':'bimodal'}[parameters['MUA_BRANCH_PREDICTOR']]
        btb = {0:'none', 1:'direct_mapped', 'none':'none', 'direct_mapped':'direct_mapped'}[parameters['MUA_BTB']]
    except (KeyError, TypeError) as error:
        raise ValueError('invalid BPU configuration selectors') from error
    predicting = mode != 'none'
    active_btb = predicting and btb != 'none'
    cf = sum(counts[k] for k in ('conditional_branches', 'direct_jumps', 'indirect_jumps'))
    conditional = counts['conditional_branches']
    def require(condition, message):
        if not condition:
            raise ValueError('inconsistent BPU statistics: '+message)
    require(cf <= retired, 'control-flow count')
    require(counts['taken_conditional_branches'] <= conditional, 'taken conditional count')
    require(counts['taken_control_flow'] == counts['taken_conditional_branches'] +
            counts['direct_jumps'] + counts['indirect_jumps'], 'taken control-flow count')
    require(counts['btb_lookups'] == (retired if active_btb else 0), 'BTB lookup denominator')
    require(counts['btb_hits'] <= counts['btb_lookups'], 'BTB hits')
    require(counts['btb_control_flow_lookups'] == (cf if active_btb else 0), 'control-flow BTB denominator')
    require(counts['btb_control_flow_hits'] <= min(counts['btb_control_flow_lookups'], counts['btb_hits']),
            'control-flow BTB hits')
    require(counts['false_btb_hits'] == counts['btb_hits'] - counts['btb_control_flow_hits'], 'false BTB hits')
    require(counts['false_btb_hits'] <= retired-cf, 'false BTB hit population')
    require(counts['direction_predictions'] == (conditional if predicting else 0), 'direction denominator')
    require(counts['direction_mispredictions'] <= counts['direction_predictions'], 'direction errors')
    require(counts['effective_direction_mispredictions'] <= counts['direction_predictions'], 'effective direction errors')
    require(counts['target_predictions'] <= counts['taken_control_flow'] and
            counts['target_mispredictions'] <= counts['target_predictions'], 'target errors')
    require(active_btb or counts['target_predictions'] == 0, 'target predictions with disabled BTB')
    require(counts['target_predictions'] <= counts['btb_control_flow_hits'], 'target predictions without BTB hit')
    require(counts['control_flow_predictions'] == (cf if predicting else 0), 'next-PC denominator')
    require(counts['control_flow_mispredictions'] <= counts['control_flow_predictions'], 'next-PC errors')
    require(counts['de_redirects'] <= retired and counts['compressed_control_flow'] <= cf, 'redirect/compressed count')
    if names == COUNTERS:
        require(counts['idata_replayed_instructions'] <= retired, 'replay retirement count')
        require((active_btb and parameters.get('MUA_BTB_IDATA_HWORDS', 1) > 0) or
                counts['idata_replayed_instructions'] == 0, 'replay with disabled instruction storage')
    counts.update(control_flow_instructions=cf, btb_misses=counts['btb_lookups']-counts['btb_hits'],
                  btb_control_flow_misses=counts['btb_control_flow_lookups']-counts['btb_control_flow_hits'])
    def percent(numerator, denominator):
        return 100*numerator/denominator if denominator else None
    rates = dict(
        btb_hit_rate=percent(counts['btb_hits'], counts['btb_lookups']),
        btb_control_flow_hit_rate=percent(counts['btb_control_flow_hits'], counts['btb_control_flow_lookups']),
        direction_accuracy=percent(counts['direction_predictions']-counts['direction_mispredictions'], counts['direction_predictions']),
        effective_direction_accuracy=percent(counts['direction_predictions']-counts['effective_direction_mispredictions'], counts['direction_predictions']),
        target_accuracy=percent(counts['target_predictions']-counts['target_mispredictions'], counts['target_predictions']),
        control_flow_next_pc_accuracy=percent(counts['control_flow_predictions']-counts['control_flow_mispredictions'], counts['control_flow_predictions']),
    )
    if names == COUNTERS:
        rates['idata_replay_rate'] = percent(counts['idata_replayed_instructions'], retired)
    return dict(schema_version=1 if names == LEGACY_COUNTERS else 2, scope=SCOPE, definition=DEFINITION,
                direction_predictor=mode, btb=btb if active_btb else 'none',
                start=begin, stop=end, counts=counts, rates_percent=rates,
                redirects_per_1000_instructions=1000*counts['de_redirects']/retired)


def validate(record, parameters, retired):
    """Recompute derived results; reject tampered counters, rates or scope."""
    if not isinstance(record, dict):
        raise ValueError('missing BPU statistics')
    names = LEGACY_COUNTERS if record.get('schema_version') == 1 else COUNTERS
    try:
        result = statistics([record['start'][name] for name in names],
                            [record['stop'][name] for name in names], parameters, retired)
    except (KeyError, TypeError) as error:
        raise ValueError('invalid BPU statistics snapshots') from error
    if result != record:
        raise ValueError('BPU statistics conflict with snapshots or scope')
    return result


def metrics(record):
    result = [dict(name='bpu_'+name, value=value, unit='events') for name, value in record['counts'].items()]
    result += [dict(name='bpu_'+name, value=value, unit='%')
               for name, value in record['rates_percent'].items() if value is not None]
    result.append(dict(name='bpu_redirects_per_1000_instructions',
                       value=record['redirects_per_1000_instructions'], unit='redirects/1000 instructions'))
    return result
