"""ELF-bound IRQ stimuli and an independent native interrupt policy checker."""
import struct

IRQ_MASK = 0x888
PRIORITY = (11, 3, 7)


def pending_interrupt(priv_m, mstatus, mie, lines):
    if priv_m and not mstatus & 8:
        return None
    return next((cause for cause in PRIORITY if lines & mie & (1 << cause)), None)


def check_interrupt_cycle(observed, *, priv_m, mstatus, mie, lines, lsu_busy, de_fire):
    """Use stimulus and prior architectural state, never DUT eligibility/cause."""
    cause = pending_interrupt(priv_m, mstatus, mie, lines)
    empty = not any(observed[k] for k in ('ex_valid_q','mem_valid_q','wb_valid_q'))
    expected = cause is not None and empty and not lsu_busy
    if bool(observed['trap_valid']) != expected:
        raise AssertionError(f'interrupt entry timing/masking/drain mismatch: expected={expected}, observed={observed}')
    if cause is not None and de_fire:
        raise AssertionError('DE admitted another instruction while interrupt drain was required')
    if expected and observed['trap_cause'] != cause:
        raise AssertionError(f'interrupt priority mismatch: expected={cause}, observed={observed["trap_cause"]}')


def interrupt_plan(image, parameters=None):
    start = image.symbols.get('uqu_interrupts')
    end = image.symbols.get('uqu_interrupts_end')
    if start is None and end is None:
        return []
    if start is None or end is None or start & 3 or not 0 < end-start <= 4096 or (end-start) % 16:
        raise ValueError('invalid uqu_interrupts ELF table boundaries')
    raw = bytes(image.memory_byte(a) for a in range(start,end))
    result, sites = [], set()
    for kind, pc, mask, reserved in struct.iter_unpack('<IIII',raw):
        if kind not in (1,2,3) or not mask or mask & ~IRQ_MASK or reserved:
            raise ValueError('invalid interrupt trigger, line mask or reserved field')
        if pc in sites or pc & (1 if image.flags & 1 else 3) or not any(
                s.flags & 1 and s.address <= pc < s.address+s.size for s in image.segments):
            raise ValueError('interrupt trigger PCs must be unique aligned executable addresses')
        if kind==3 and parameters is not None and not parameters['ISA_M']:
            raise ValueError('multi-cycle interrupt trigger requires ISA_M')
        sites.add(pc)
        result.append(dict(kind=kind,pc=pc,mask=mask))
    return result


class InterruptStimulus:
    """Hold each declared mask; acknowledge one source per accepted interrupt."""
    def __init__(self, plan):
        self.plan = plan
        self.index, self.lines = 0, 0
        self.assertions, self.entries = [], []

    def assert_next(self, cycle, order, context):
        if self.lines or self.index >= len(self.plan):
            raise ValueError('interrupt request is active or no declared trigger remains')
        self.lines = self.plan[self.index]['mask']
        self.assertions.append(dict(index=self.index, cycle=cycle, order=order,
                                    context=context, **self.plan[self.index]))

    def accept(self, pc, cause, cycle, order):
        if not self.lines or self.index >= len(self.plan):
            raise AssertionError('undeclared external interrupt')
        expected = next(c for c in PRIORITY if self.lines & (1 << c))
        if cause != expected:
            raise AssertionError(f'declared interrupt order mismatch: {cause} != {expected}')
        self.entries.append(dict(index=self.index, pc=pc, cause=cause, mask=self.lines,
                                 cycle=cycle, order=order))
        self.lines &= ~(1 << cause)
        if not self.lines: self.index += 1

    def finish(self):
        if self.index != len(self.plan) or self.lines:
            raise AssertionError('missing declared interrupt triggers/entries')

    def evidence(self):
        return dict(schema_version=1, plan=self.plan, assertions=self.assertions,
                    entries=self.entries, completed=self.index==len(self.plan) and not self.lines)


def replay_masks(records, audit, plan):
    """Validate external stimulus evidence before the reference consumes it."""
    if (audit.get('schema_version') != 1 or audit.get('plan') != plan or not audit.get('completed') or
            len(audit.get('assertions',[])) != len(plan)):
        raise ValueError('incomplete or mismatched interrupt stimulus evidence')
    for index,row in enumerate(audit['assertions']):
        if row.get('index') != index or any(row.get(k) != v for k,v in plan[index].items()):
            raise ValueError('interrupt assertion differs from ELF declaration')
        if any(type(row.get(k)) is not int or row[k]<0 for k in ('cycle','order')):
            raise ValueError('invalid interrupt assertion time/order')
        context=row.get('context',{})
        if not ({1:context.get('retired_pc')==row['pc'],2:context.get('dmem_pending') is True,
                 3:context.get('multicycle_active') is True}[row['kind']]):
            raise ValueError('interrupt assertion lacks its declared trigger context')
    entries = iter(audit.get('entries',[]))
    stimulus = InterruptStimulus(plan)
    masks, order = [], 0
    for row in records:
        if row['type']=='reset': continue
        if row['type']=='instruction':
            order+=1
            masks.append(0)
            continue
        entry=next(entries,None)
        if entry is None or (entry['pc'],entry['cause'],entry['order']) != (row['pc'],row['cause'],order):
            raise ValueError('interrupt stimulus evidence and RVFI boundary disagree')
        if not stimulus.lines:
            assertion=audit['assertions'][stimulus.index]
            stimulus.assert_next(assertion['cycle'],assertion['order'],assertion['context'])
        if entry['mask'] != stimulus.lines or entry['index'] != stimulus.index:
            raise ValueError('interrupt input mask does not follow declared acknowledgements')
        assertion=audit['assertions'][stimulus.index]
        if (type(entry.get('cycle')) is not int or entry['cycle']<assertion['cycle'] or
                entry['order']<assertion['order']):
            raise ValueError('interrupt acceptance precedes its assertion')
        masks.append(stimulus.lines)
        stimulus.accept(row['pc'],row['cause'],entry['cycle'],order)
    if next(entries,None) is not None: raise ValueError('extra interrupt stimulus evidence')
    stimulus.finish()
    return masks
