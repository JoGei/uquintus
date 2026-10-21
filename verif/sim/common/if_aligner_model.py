"""Byte-window oracle shared by standalone alignment and real prefetch tests."""

MASK = (1 << 32)-1


def select(i, compressed_enabled):
    pc = i['pc']
    o = dict(valid=0,instr=0,compressed=0,next_pc=pc,drop_word=0,word1_needed=0,
             misaligned=int(bool(i['valid'] and pc % (2 if compressed_enabled else 4))),
             exception_valid=0,exception_cause=0,exception_tval=0)
    if not i['valid'] or o['misaligned'] or not i['word0_valid']:
        return o
    if i['word0_error']:
        o.update(valid=1,exception_valid=1,exception_cause=1,exception_tval=pc)
        return o
    window = i['word0_data'].to_bytes(4,'little')+i['word1_data'].to_bytes(4,'little')
    offset = pc % 4
    width = 2 if compressed_enabled and window[offset] % 4 != 3 else 4
    positions = range(offset,offset+width)
    required = {position//4 for position in positions}
    o['word1_needed'] = int(1 in required)
    if any(not i[f'word{word}_valid'] for word in required):
        return o
    for position in positions:
        if i[f'word{position//4}_error']:
            o.update(valid=1,exception_valid=1,exception_cause=1,
                     exception_tval=(pc+position-offset)&MASK)
            return o
    next_pc = (pc+width)&MASK
    o.update(valid=1,instr=int.from_bytes(window[offset:offset+width],'little'),
             compressed=int(width==2),next_pc=next_pc,
             drop_word=int(pc//4 != next_pc//4))
    return o
