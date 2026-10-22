"""Age-ordered transaction oracle; fence synchronization is a three-state protocol."""

STAGES = ('de','ex','mem','wb')
OUTPUTS = ('if_permit','fetch_enable','if_ready','de_permit','de_ready','ex_ready',
    'mem_ready','wb_ready','if_fire','de_fire','ex_fire','mem_fire','wb_fire',
    'de_enable','ex_enable','mem_enable','wb_enable','de_valid_next','ex_valid_next',
    'mem_valid_next','wb_valid_next','if_flush','de_flush','ex_flush','mem_flush',
    'mem_request_permit','irq_eligible','draining','trap_valid','trap_pc','trap_interrupt',
    'trap_cause','trap_tval','drain_accept','drain_pc','redirect_valid','redirect_addr',
    'fence_req','fencei_req')


class ControlModel:
    def __init__(self, fencei):
        self.fencei = fencei
        self.fence = 'idle'

    def evaluate(self, i):
        o = dict.fromkeys(OUTPUTS,0)
        if not i['rst_n']:
            return o
        occupied = [bool(i[name+'_valid']) for name in STAGES]
        faults = {n for n,name in enumerate(STAGES) if occupied[n] and i[name+'_exception']}
        serial = {n for n,name in enumerate(STAGES) if n and occupied[n] and i[name+'_serialize']}
        pending = [cause for cause in (11,3,7) if (i['mie']//(2**cause))%2 and (i['mip']//(2**cause))%2]
        eligible = bool(pending and not i['irq_mask'] and
                        (not i['priv_m'] or (i['mstatus']//8)%2))
        o['irq_eligible'] = int(eligible)
        o['draining'] = int(bool(eligible or i['drain_req']))
        fence_kind = i['wb_system'] if occupied[3] else 0
        if fence_kind==7 and not self.fencei:
            fence_kind = 0
        request = fence_kind in (6,7) and 3 not in faults and self.fence!='acked' and (
            self.fence=='waiting' or i['data_idle'])
        o['fence_req'] = int(request and fence_kind==6)
        o['fencei_req'] = int(request and fence_kind==7)
        acknowledged = request and i['fence_ack' if fence_kind==6 else 'fencei_ack']
        synchronization = 3 in faults or fence_kind not in (6,7) or self.fence=='acked' or acknowledged
        o['wb_ready'] = int(bool(i['commit_enable'] and synchronization))
        o['wb_fire'] = int(bool(occupied[3] and i['wb_complete'] and o['wb_ready']))
        recovery = None
        if o['wb_fire']:
            if i['wb_redirect_valid']:
                recovery = i['wb_redirect_addr']
            elif fence_kind==7 and 3 not in faults:
                recovery = i['wb_next_pc']
        boundary = not any(occupied[1:]) and i['drain_ready']
        boundary_pc = i['de_pc'] if occupied[0] else i['resume_pc']
        if boundary and recovery is None:
            if i['drain_req']:
                o.update(drain_accept=1,drain_pc=boundary_pc)
                recovery = i['drain_target']
            elif eligible:
                cause = pending[0]
                o.update(trap_valid=1,trap_interrupt=1,trap_pc=boundary_pc,trap_cause=cause)
                base = i['mtvec']//4*4
                recovery = (base+(4*cause if i['mtvec']%4==1 else 0))&0xFFFFFFFF
        # Each fault cancels only younger transactions; an accepted WB event
        # cancels all three younger slots, without flushing its own acceptance.
        killed = {n for n in range(3) if any(age>n for age in faults)}
        if recovery is not None and o['wb_fire']:
            killed.update((0,1,2))
        if o['trap_valid'] or o['drain_accept']:
            killed.add(0)
        for n,name in enumerate(STAGES[:3]):
            o[name+'_flush'] = int(n in killed)
        # Work backwards from commit capacity so older work can always drain.
        for n in (2,1):
            successor = STAGES[n+1]
            name = STAGES[n]
            room = not occupied[n+1] or o[successor+'_fire']
            o[name+'_ready'] = int(room and n not in killed)
            o[name+'_fire'] = int(bool(occupied[n] and i[name+'_complete'] and o[name+'_ready']))
        admit = bool(i['de_admit'] and not o['draining'] and not any(n>0 for n in faults)
                     and not serial and not (o['wb_fire'] and recovery is not None))
        o['de_permit'] = int(admit)
        o['de_ready'] = int(admit and (not occupied[1] or o['ex_fire']))
        o['de_fire'] = int(bool(occupied[0] and i['de_complete'] and o['de_ready']))
        branch = bool(o['de_fire'] and i['de_redirect'] and 0 not in faults)
        if recovery is None and branch:
            recovery = i['de_redirect_addr']
        o['if_permit'] = int(not faults and not o['draining'] and recovery is None)
        o['if_ready'] = int(o['if_permit'] and (not occupied[0] or o['de_fire']))
        o['if_fire'] = int(bool(i['if_valid'] and o['if_ready']))
        fetch_barrier = self.fencei and any(occupied[n] and i[name+'_system']==7 for n,name in enumerate(STAGES))
        o['fetch_enable'] = int(o['if_permit'] and not fetch_barrier)
        o['if_flush'] = int(bool(faults or recovery is not None))
        o['mem_request_permit'] = int(occupied[2] and 2 not in faults and 3 not in faults and
            not (o['wb_fire'] and recovery is not None) and (not occupied[3] or i['wb_effect_safe']))
        for n,name in enumerate(STAGES):
            o[name+'_enable'] = int(n in killed or not occupied[n] or o[name+'_fire'])
            incoming = o['if_fire'] if n==0 else o[STAGES[n-1]+'_fire']
            o[name+'_valid_next'] = int(n not in killed and bool(incoming))
        if recovery is not None:
            o.update(redirect_valid=1,redirect_addr=recovery)
        return o

    def advance(self, i, o):
        if not i['rst_n'] or not i['wb_valid'] or o['wb_fire'] or i['wb_exception']:
            self.fence = 'idle'
        elif o['fence_req'] or o['fencei_req']:
            kind = 'fence_ack' if o['fence_req'] else 'fencei_ack'
            self.fence = 'acked' if i[kind] else 'waiting'
