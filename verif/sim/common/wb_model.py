"""WB architectural effects and in-order standard CV-X-IF completion model."""

from csregfile_model import CSRModel, INPUTS

FIELDS = ('kind', 'result', 'rd_we', 'rd', 'pc', 'instr', 'csr_addr', 'csr_op',
          'csr_src', 'csr_src_zero', 'fflags_valid', 'fflags', 'exception_valid',
          'exception_cause', 'exception_tval', 'xif_id')
GLOBALS = dict(lsu=0, lsu_res_valid=0, lsu_res_registered=0, lsu_res_data=0,
               lsu_res_forward_data=0,
               lsu_res_exception_valid=0, lsu_res_exception_cause=0, lsu_res_exception_tval=0, rst_n=1, flush=0, valid=1, ready=1, priv_m=1, hart_id=0xCAFEBABE,
               irq_software=0, irq_timer=0, irq_external=0, trap=0,
               trap_pc=0, trap_interrupt=0, trap_cause=0, trap_tval=0,
               debug_mode=0, debug_enter=0, debug_pc=0, debug_cause=3,
               xif_kill_valid=0, xif_kill_id=0, xif_result_valid=0,
               xif_result_id=0, xif_result_hartid=0xCAFEBABE,
               xif_result_data=0, xif_result_rd=0, xif_result_we=0)


def token(**updates):
    item = dict(kind=0, result=0, rd_we=1, rd=1, pc=0x8000, instr=0x00108093,
                csr_addr=0x340, csr_op=2, csr_src=0, csr_src_zero=1,
                fflags_valid=0, fflags=0, exception_valid=0, exception_cause=0,
                exception_tval=0, xif_id=0)
    item.update(updates)
    return item


class WBModel:
    def __init__(self, params):
        self.p = params
        self.csr = CSRModel(params)
        self.gprs = [None] * 32
        self.gprs[0] = 0
        self.committed = False

    def evaluate(self, item, g):
        live = bool(g['rst_n'] and not g['flush'] and g['valid'])
        debug = bool(self.p['DEBUG'] and g['debug_mode'])
        external_debug = bool(g['rst_n'] and self.p['DEBUG'] and g['debug_enter'] and not debug)
        external_trap = bool(g['rst_n'] and g['trap'] and not debug and not external_debug)
        xif = bool(self.p['XIF'] and item['kind'] == 3)
        debug_break = bool(self.p['DEBUG'] and item['kind'] == 5 and
                           (debug or self.csr.words[0x7B0] & (1 << (15 if g['priv_m'] else 12))))
        destination = bool((item['kind'] == 0 and item['rd_we']) or item['kind'] == 1)
        bad = ((item['kind'] == 3 and not self.p['XIF']) or
               (item['kind'] == 2 and (not g['priv_m'] or debug)) or
               (item['kind'] == 4 and not debug) or item['kind'] > 5 or
               (self.p['ISA_E'] and destination and item['rd'] >= 16) or
               (item['fflags_valid'] and (not self.p['ISA_ZFINX'] or item['kind'] != 0)))
        ci = dict(INPUTS)
        ci.update({n: g[n] for n in ('rst_n', 'flush', 'priv_m', 'hart_id',
                                    'irq_software', 'irq_timer', 'irq_external', 'debug_mode')})
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
        elif g['lsu'] and g['lsu_res_valid'] and g['lsu_res_exception_valid']:
            fault = g['lsu_res_exception_cause'], g['lsu_res_exception_tval']
        elif item['kind'] == 5 and not debug_break:
            fault = 3, 0
        else:
            fault = None
        notify = bool(self.p['XIF'] and g['rst_n'] and g['valid'] and xif and not self.committed and
                      (g['flush'] or (not external_trap and not external_debug and (fault is None or g['ready']))))
        pair = bool(self.p.get('XIF_DUALWRITE', 0) and g['xif_result_we'] & 2)
        packet_ok = (not pair or g['xif_result_we'] & 1) and (
            not g['xif_result_we'] & 1 or (g['xif_result_rd'] == item['rd'] and
                (not self.p['ISA_E'] or g['xif_result_rd'] < 16) and
                (not pair or g['xif_result_rd'] % 2 == 0)))
        completion = (not xif or fault is not None or
                      ((self.committed or notify) and g['xif_result_valid'] and
                       g['xif_result_id'] == item['xif_id'] and
                       g['xif_result_hartid'] == g['hart_id'] and packet_ok))
        completion = completion and (not g['lsu'] or g['lsu_res_valid'])
        valid = live and not external_trap and not external_debug and completion
        accepted = bool(valid and g['ready'])
        retired = bool(accepted and fault is None and not debug_break)
        exception_fire = bool(accepted and fault is not None and not debug)
        local_debug = bool(accepted and fault is None and debug_break)
        dest = (bool(g['xif_result_we'] & 1) and g['xif_result_rd'] != 0) if xif else (destination and item['rd'] != 0)
        rd = g['xif_result_rd'] if xif else item['rd']
        value = (g['xif_result_data'] & 0xFFFFFFFF) if xif else cr['rdata'] if item['kind'] == 1 else g['lsu_res_data'] if g['lsu'] else item['result']
        forward = bool(valid and fault is None and dest and (item['kind'] != 1 or retired) and
                       (not g['lsu'] or g['lsu_res_registered']))
        commit = bool(self.p['XIF'] and g['rst_n'] and (notify or g['xif_kill_valid']))
        result = dict(lsu_res_ready=int(live and g['lsu'] and not external_trap and not external_debug and g['ready']), valid=int(valid), ready=int(g['rst_n'] and not g['flush'] and not external_trap and not external_debug and
                                                (not g['valid'] or accepted)),
                      retire=int(retired), exception_fire=int(exception_fire), mret=int(retired and item['kind'] == 2),
                      dret=int(retired and item['kind'] == 4), debug_enter=int(external_debug or (local_debug and not debug)),
                      debug_exception=int(accepted and fault is not None and debug), debug_ebreak=int(local_debug and debug),
                      exception_valid=int(live and fault is not None),
                      exception_cause=fault[0] if live and fault else 0,
                      exception_tval=fault[1] if live and fault else 0,
                      exception_pc=item['pc'] if live and fault else 0,
                      result_valid=int(forward), result=(g['lsu_res_forward_data'] if g['lsu'] else value) if forward else 0,
                      we0=int(retired and dest), waddr0=rd if retired and dest else 0,
                      wdata0=value if retired and dest else 0,
                      we1=int(retired and dest and xif and pair),
                      waddr1=rd+1 if retired and dest and xif and pair else 0,
                      wdata1=(g['xif_result_data'] >> 32) if retired and dest and xif and pair else 0,
                      xif_commit_valid=int(commit), xif_commit_hartid=g['hart_id'] if commit else 0,
                      xif_commit_id=(item['xif_id'] if notify else g['xif_kill_id']) if commit else 0,
                      xif_commit_kill=int(commit and ((g['flush'] or fault is not None) if notify else True)),
                      xif_kill_ready=int(self.p['XIF'] and g['rst_n'] and not notify),
                      xif_result_ready=int(live and xif and fault is None and not external_trap and
                                           not external_debug and (self.committed or notify) and g['ready']))
        ci.update(retire=int(retired), csr_commit=int(retired and item['kind'] == 1),
                  trap=int(external_trap or exception_fire), trap_pc=g['trap_pc'] if external_trap else item['pc'],
                  trap_interrupt=g['trap_interrupt'] if external_trap else 0,
                  trap_cause=g['trap_cause'] if external_trap else result['exception_cause'],
                  trap_tval=g['trap_tval'] if external_trap else result['exception_tval'], mret=result['mret'],
                  debug_enter=result['debug_enter'], debug_pc=g['debug_pc'] if external_debug else item['pc'],
                  debug_cause=g['debug_cause'] if external_debug else 1, debug_ebreak=int(local_debug and not debug),
                  dret=result['dret'], fp_flags_valid=int(retired and item['kind'] == 0 and item['fflags_valid']), fp_flags=item['fflags'])
        return result, ci

    def step(self, item, g):
        result, ci = self.evaluate(item, g)
        for n in (0, 1):
            if result[f'we{n}']:
                self.gprs[result[f'waddr{n}']] = result[f'wdata{n}']
        if not g['rst_n'] or g['flush'] or result['valid'] and g['ready']:
            self.committed = False
        elif result['xif_commit_valid'] and not result['xif_commit_kill']:
            self.committed = True
        self.csr.step(ci)
        return result
