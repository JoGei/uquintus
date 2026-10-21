"""Architectural operand-source model using ordered producer transactions."""


class HazardModel:
    def __init__(self, params):
        self.p = params
        self.third = bool(params['ISA_ZFINX'] or
                          (params['XIF'] and params['XIF_NUM_RS'] == 3))
        self.dual = bool(params['XIF'] and params['XIF_DUALWRITE'])
        self.retained = [None] * 3

    def sources(self, i, consumer):
        # Consumers see only older transactions, youngest first. No result
        # filtering here: an unavailable youngest writer still owns the source.
        stages = ('ex', 'mem', 'wb') if consumer == 'de' else ('mem', 'wb')
        return [dict(stage=s, destinations=[
            i[s+'_rd'+str(n)] if i[s+'_pending'] & (1 << n) and (n == 0 or self.dual)
            else None for n in range(2)],
            available=bool(i[s+'_result_available'] and i[s+'_result_forwardable']),
            value=i[s+'_result'], advances=bool(i[s+'_advance']))
            for s in stages if i[s+'_valid']]

    def route(self, stage, consumer):
        return bool(self.p['MUA_FORWARDING'] and
                    (stage == 'wb' and consumer == 'de' or
                     self.p['MUA_FORWARD_'+stage.upper()+'_TO_'+consumer.upper()]))

    def resolve(self, i, consumer, slot):
        prefix = consumer+'_rs'+str(slot)
        reg = i[prefix+'_addr']
        if (not i['rst_n'] or not i[consumer+'_valid'] or
                not i[consumer+'_rs_used'] & (1 << slot) or
                slot == 2 and not self.third or self.p['ISA_E'] and reg >= 16):
            return 0, False, False
        if reg == 0:
            return 0, True, False
        if consumer == 'de' and self.retained[slot] is not None:
            return self.retained[slot], True, False
        if consumer == 'ex' and i['ex_rs_captured'] & (1 << slot):
            return i[prefix], True, False
        owner = next((producer for producer in self.sources(i, consumer)
                      if reg in producer['destinations']), None)
        if owner is None:
            return (i[prefix], True, False) if consumer == 'de' else (0, False, False)
        primary = owner['destinations'][0] == reg
        ready = primary and owner['available'] and self.route(owner['stage'], consumer)
        if ready:
            return owner['value'], True, False
        guarantee = False
        if (consumer == 'de' and primary and owner['available'] and
                not i['de_rs_need_now'] & (1 << slot)):
            future = {'ex': 'mem', 'mem': 'wb'}.get(owner['stage']) if owner['advances'] else owner['stage']
            # EX cannot forward from itself; advancing to MEM is necessary.
            if future in ('mem', 'wb'):
                guarantee = self.route(future, 'ex')
        return 0, False, guarantee

    def outputs(self, i):
        result = {}
        for consumer in ('de', 'ex'):
            ready = guarantee = 0
            for slot in range(3):
                value, available, promised = self.resolve(i, consumer, slot)
                result[consumer+'_rs'+str(slot)] = value
                ready |= int(available) << slot
                guarantee |= int(promised) << slot
            result[consumer+'_rs_ready'] = ready
            if consumer == 'de':
                result['de_rs_ex_guaranteed'] = guarantee
        return result

    def edge(self, i):
        before = self.outputs(i)
        if not i['rst_n'] or i['de_clear'] or not i['de_valid']:
            self.retained = [None] * 3
        elif self.p['MUA_DE_OPERAND_RETENTION']:
            for n in range(3):
                if (self.retained[n] is None and before['de_rs_ready'] & (1 << n)
                        and i['de_rs'+str(n)+'_addr'] != 0):
                    self.retained[n] = before['de_rs'+str(n)]


def defaults():
    i = dict(rst_n=1, de_valid=1, de_clear=0, ex_valid=1,
             de_rs_used=7, de_rs_need_now=0, ex_rs_used=7, ex_rs_captured=0)
    for consumer in ('de', 'ex'):
        for n in range(3):
            i[consumer+'_rs'+str(n)+'_addr'] = n+1
            i[consumer+'_rs'+str(n)] = 0x100+n
    for stage in ('ex', 'mem', 'wb'):
        i.update({stage+'_valid': 1, stage+'_pending': 0, stage+'_rd0': 0,
                  stage+'_rd1': 0, stage+'_result_available': 0,
                  stage+'_result_forwardable': 0, stage+'_result': 0,
                  stage+'_advance': 0})
    return i
