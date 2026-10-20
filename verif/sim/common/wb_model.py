"""WB architectural outcomes using the shared CSR-word reference model."""

from csregfile_model import CSRModel, INPUTS

FIELDS = ('kind', 'result', 'rd_we', 'rd', 'pc', 'instr', 'csr_addr', 'csr_op',
          'csr_src', 'csr_src_zero', 'fflags_valid', 'fflags', 'exception_valid',
          'exception_cause', 'exception_tval')
GLOBALS = dict(rst_n=1, flush=0, valid=1, ready=1, priv_m=1, hart_id=0xCAFEBABE,
               irq_software=0, irq_timer=0, irq_external=0, trap=0,
               trap_pc=0, trap_interrupt=0, trap_cause=0, trap_tval=0)


def token(**updates):
    item = dict(kind=0, result=0, rd_we=1, rd=1, pc=0x8000, instr=0x00108093,
                csr_addr=0x340, csr_op=2, csr_src=0, csr_src_zero=1,
                fflags_valid=0, fflags=0, exception_valid=0, exception_cause=0,
                exception_tval=0)
    item.update(updates)
    return item


class WBModel:
    def __init__(self, params):
        self.p = params
        self.csr = CSRModel(params)
        self.gprs = [None] * 32
        self.gprs[0] = 0

    def evaluate(self, item, g):
        live = bool(g['rst_n'] and not g['flush'] and g['valid'])
        destination = bool((item['kind'] == 0 and item['rd_we']) or item['kind'] == 1)
        bad = (item['kind'] == 3 or (item['kind'] == 2 and not g['priv_m']) or
               (self.p['ISA_E'] and destination and item['rd'] >= 16) or
               (item['fflags_valid'] and (not self.p['ISA_ZFINX'] or item['kind'] != 0)))
        ci = dict(INPUTS)
        ci.update({n: g[n] for n in ('rst_n', 'flush', 'priv_m', 'hart_id',
                                    'irq_software', 'irq_timer', 'irq_external')})
        ci.update(csr_valid=int(live and item['kind'] == 1 and not item['exception_valid'] and not bad),
                  csr_commit=0, csr_addr=item['csr_addr'], csr_op=item['csr_op'],
                  csr_src=item['csr_src'], csr_src_zero=item['csr_src_zero'],
                  csr_rd_zero=int(item['rd'] == 0), csr_instr=item['instr'])
        cr, _ = self.csr.query(ci)
        if item['exception_valid']:
            fault = item['exception_cause'], item['exception_tval']
        elif bad:
            fault = 2, item['instr']
        elif cr['exception_valid']:
            fault = cr['exception_cause'], cr['exception_tval']
        else:
            fault = None
        valid = live and not g['trap']
        accepted = valid and g['ready']
        retired = bool(accepted and fault is None)
        exception_fire = bool(accepted and fault is not None)
        dest = destination and item['rd'] != 0
        forward = bool(valid and fault is None and dest and (item['kind'] != 1 or retired))
        value = cr['rdata'] if item['kind'] == 1 else item['result']
        result = dict(valid=int(valid), ready=int(g['rst_n'] and not g['flush'] and not g['trap'] and
                                                (not g['valid'] or g['ready'])),
                      retire=int(retired), exception_fire=int(exception_fire),
                      mret=int(retired and item['kind'] == 2),
                      exception_valid=int(live and fault is not None),
                      exception_cause=fault[0] if live and fault else 0,
                      exception_tval=fault[1] if live and fault else 0,
                      exception_pc=item['pc'] if live and fault else 0,
                      result_valid=int(forward), result=value if forward else 0,
                      we0=int(retired and dest), waddr0=item['rd'] if retired and dest else 0,
                      wdata0=value if retired and dest else 0, we1=0, waddr1=0, wdata1=0)
        external = bool(g['rst_n'] and g['trap'])
        ci.update(retire=int(retired), csr_commit=int(retired and item['kind'] == 1),
                  trap=int(external or exception_fire),
                  trap_pc=g['trap_pc'] if external else item['pc'],
                  trap_interrupt=g['trap_interrupt'] if external else 0,
                  trap_cause=g['trap_cause'] if external else result['exception_cause'],
                  trap_tval=g['trap_tval'] if external else result['exception_tval'],
                  mret=result['mret'], fp_flags_valid=int(retired and item['kind'] == 0 and item['fflags_valid']),
                  fp_flags=item['fflags'])
        return result, ci

    def step(self, item, g):
        result, ci = self.evaluate(item, g)
        if result['we0']:
            self.gprs[item['rd']] = result['wdata0']
        self.csr.step(ci)
        return result
