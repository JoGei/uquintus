"""Instruction-level MEM expectations shared by stage and parent fixtures."""

from lsu_model import ByteMemory, local_exception

FIELDS = ('lsu', 'we', 'op', 'result', 'store_data', 'instr', 'priv_m',
          'fflags_valid', 'fflags', 'exception_valid', 'exception_cause', 'exception_tval')
OUTPUTS = ('result', 'fflags_valid', 'fflags', 'exception_valid',
           'exception_cause', 'exception_tval', 'load_result_valid')


def token(**updates):
    item = dict(lsu=0, we=0, op=2, result=0, store_data=0, instr=0x00108093,
                priv_m=1, fflags_valid=0, fflags=0, exception_valid=0,
                exception_cause=0, exception_tval=0, pc=0x8000, rd=1)
    item.update(updates)
    return item


def request(item, allow=True):
    return dict(we=item['we'], op=item['op'], addr=item['result'],
                wdata=item['store_data'], instr=item['instr'], access_fault=int(not allow))


def outcome(item, memory, allow=True, error=False):
    if item['exception_valid']:
        return 0, 0, 0, 1, item['exception_cause'], item['exception_tval'], 0
    if item['lsu']:
        data, fault, cause, value = memory.result(request(item, allow), error)
        return data, 0, 0, fault, cause, value, int(not fault and not item['we'])
    flags_valid = item['fflags_valid']
    return item['result'], flags_valid, item['fflags'] if flags_valid else 0, 0, 0, 0, 0
