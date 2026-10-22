"""Clock-based counter evidence, independent of the ISA model's timing."""

MASK = 0xffffffff
MASK64 = (1 << 64) - 1
COUNTERS = {0xb00:'mcycle', 0xb80:'mcycle', 0xc00:'mcycle', 0xc80:'mcycle',
            0xb02:'minstret', 0xb82:'minstret', 0xc02:'minstret', 0xc82:'minstret'}
SAMPLED_CSRS = {*COUNTERS, 0x344}


def counter_state(model):
    return dict(mcycle=model.cycle, minstret=model.instret,
                mcountinhibit=model.words[0x320])


def check_counters(actual, expected):
    if actual != expected:
        raise AssertionError(f'clock counter mismatch: actual={actual}, expected={expected}')


def replay_samples(records, audit, irq_audit):
    """Recompute counter progression and pin levels before accepting replay data.

    Values come from the native oracle, not RVFI destination results. Validate
    all event gaps, explicit writes, aliases, reset baseline and IRQ evidence.
    The simulator additionally compares actual RTL counters on *every* edge.
    """
    events = [r for r in records if r['type'] != 'reset']
    if (audit.get('schema_version') != 1 or audit.get('status') != 'passed' or
            len(audit.get('events', [])) != len(events)):
        raise ValueError('missing or failed clock counter evidence')
    reset = audit.get('reset_cycle')
    checked = audit.get('checked_cycles')
    if type(reset) is not int or reset < 0 or type(checked) is not int or checked < 1:
        raise ValueError('invalid counter reset/clock coverage')
    previous_cycle = reset
    state = dict(mcycle=0, minstret=0, mcountinhibit=0)
    samples = []
    for index, (row, event) in enumerate(zip(audit['events'], events)):
        for phase in ('before','after'):
            values=row.get(phase)
            if (not isinstance(values,dict) or set(values)!=set(state) or
                    any(type(v) is not int or not 0 <= v <= MASK64 for v in values.values())):
                raise ValueError('invalid counter state/width')
        cycle = row.get('cycle')
        if type(cycle) is not int or not previous_cycle < cycle <= reset+checked:
            raise ValueError('counter event clock order/coverage mismatch')
        pc = event['pc'] if event['type']=='interrupt' else event['rvfi_pc_rdata']
        if (row.get('index'), row.get('type'), row.get('pc')) != (index, event['type'], pc):
            raise ValueError('counter evidence and RVFI event disagree')
        before = dict(state)
        if not state['mcountinhibit'] & 1:
            before['mcycle'] = (before['mcycle'] + cycle-previous_cycle-1) & MASK64
        if row.get('before') != before:
            raise ValueError('counter pre-state disagrees with clock/retirement progression')
        lines = 0
        for assertion in irq_audit.get('assertions', []):
            if assertion['cycle'] <= cycle: lines |= assertion['mask']
        for entry in irq_audit.get('entries', []):
            if entry['cycle'] < cycle:
                # Later assertions may reassert a previously acknowledged bit.
                if not any(a['cycle'] > entry['cycle'] and a['cycle'] <= cycle and
                           a['mask'] & (1 << entry['cause']) for a in irq_audit.get('assertions', [])):
                    lines &= ~(1 << entry['cause'])
        if row.get('mip') != lines:
            raise ValueError('sampled MIP disagrees with declared IRQ pin timing')
        state = dict(before)
        if not before['mcountinhibit'] & 1: state['mcycle'] = (state['mcycle']+1) & MASK64
        retired = event['type']=='instruction' and not event['rvfi_trap']
        if retired and not before['mcountinhibit'] & 4:
            state['minstret'] = (state['minstret']+1) & MASK64
        if retired:
            insn = event['rvfi_insn']
            addr, op, rs = insn >> 20, insn >> 12 & 7, insn >> 15 & 31
            if insn & 127 == 0x73 and op and (op & 3 == 1 or rs):
                source = rs if op & 4 else event['rvfi_rs1_rdata']
                name = COUNTERS.get(addr)
                if name or addr==0x320:
                    shift = 32 if name and addr & 0x80 else 0
                    old = before[name] >> shift & MASK if name else before['mcountinhibit']
                    value = source if op & 3 == 1 else old | source if op & 3 == 2 else old & ~source
                    if name:
                        state[name] = (before[name] & ~(MASK << shift)) | ((value & MASK) << shift)
                    else: state['mcountinhibit'] = value & 5
        if row.get('after') != state:
            raise ValueError('counter post-state disagrees with retirement/write semantics')
        samples.append(dict(**before, mip=lines))
        previous_cycle = cycle
    if not events or previous_cycle != reset+checked:
        raise ValueError('counter evidence does not cover the final execution edge')
    return samples
