"""DE contract model: ISA oracle, use points, branch semantics and local XIF state."""
from decode_model import decode

MASK = (1 << 32)-1


def inputs(**changes):
    i = dict(rst_n=1, flush=0, valid=1, ready=1, permit=1, pc=0x1000,
             instr=0x13, original_instr=0x13, compressed=0, priv_m=1,
             debug_mode=0, tw=0, frm=0, exception_valid=0, exception_cause=0,
             exception_tval=0, rs0=0xA5A5, rs1=0x5A5A, rs2=0x1234,
             rs_ready=7, rs_ex_guaranteed=0, xif_force=0, xif_id_valid=1, xif_id=2,
             hart_id=0, xif_cleanup_ready=1, xif_issue_ready=0,
             xif_issue_accept=0, xif_issue_writeback=0,
             xif_issue_register_read=0, xif_register_ready=0)
    i.update(changes)
    if 'instr' in changes and 'original_instr' not in changes:
        i['original_instr'] = changes['instr']
    return i


class DEModel:
    def __init__(self, params):
        self.p = params
        self.clear()

    def clear(self):
        self.issued = self.accepted = self.bad = self.cleaned = False
        self.writeback = 0
        self.operands = [None]*self.p['XIF_NUM_RS']

    def evaluate(self, i):
        d, _ = decode(i['instr'], self.p)
        if self.p['XIF'] and i['xif_force']:
            d.update(native=0, branch=0, pass_link=0)
        active = bool(i['rst_n'] and not i['flush'] and i['valid'])
        debug = bool(self.p['DEBUG'] and i['debug_mode'])
        machine = bool(not self.p['ISA_UMODE'] or i['priv_m'] or debug)
        rm = i['frm'] if d['rm'] == 7 else d['rm']
        restricted = (d['system'] == 3 and (not machine or debug) or
                      d['system'] == 4 and not debug or
                      d['system'] == 5 and not machine and i['tw'])
        early = (i['exception_valid'] or i['compressed'] and not self.p['ISA_C'] or
                 self.p['XIF'] and i['xif_force'] and (not self.p['ISA_C'] or not i['compressed']) or
                 d['native'] and (d['illegal'] or restricted or d['fu'] == 2 and d['rm'] == 7 and rm > 4))
        offer = bool(self.p['XIF'] and not d['native'] and not early)
        native = bool(active and d['native'] and not early)
        source_used = d['rs_used'] if native else (1 << self.p['XIF_NUM_RS'])-1 if active and offer and not self.issued else 0
        need_now = source_used if not native or d['branch'] or d['wb_kind'] == 1 else 0
        ex_used = d['rs_used'] if native and d['fu'] != 3 else 0
        ready_now = i['rs_ready'] & need_now == need_now
        ready_ex = (i['rs_ready'] | i['rs_ex_guaranteed']) & ex_used == ex_used
        addresses = [d['rs1'], d['rs2'], d['rs3']] if native else [0]*3
        if active and offer and not self.issued:
            addresses = [(i['instr'] >> 15) & 31, (i['instr'] >> 20) & 31,
                         (i['instr'] >> 7) & 31 if self.p['XIF_NUM_RS'] == 3 else 0]
        sequential = (i['pc']+(2 if i['compressed'] and self.p['ISA_C'] else 4)) & MASK
        target = 0
        taken = False
        branch_bad = False
        if d['branch']:
            target = ((i['rs0'] if d['branch'] == 3 else i['pc'])+d['imm']) & MASK
            if d['branch'] == 3:
                target &= ~1
            signed = lambda v: v if v < 1 << 31 else v-(1 << 32)
            a, b = i['rs0'], i['rs1']
            compare = {0:a == b, 1:a != b, 4:signed(a) < signed(b), 5:signed(a) >= signed(b), 6:a < b, 7:a >= b}
            taken = d['branch'] in (2,3) or compare[d['branch_op']]
            branch_bad = taken and target % (2 if self.p['ISA_C'] else 4) != 0
        unknown = not d['native'] and (not self.p['XIF'] or self.issued and (not self.accepted or self.bad))
        fault = bool(early or unknown or native and ready_now and branch_bad or native and d['system'] == 1)
        cleanup = bool(active and self.issued and (not self.accepted or self.bad) and not self.cleaned)
        clean = self.cleaned or cleanup and i['xif_cleanup_ready']
        complete = (not self.issued or clean) if fault else (
            self.issued and (self.accepted and not self.bad or clean)) if offer else ready_now and ready_ex
        valid = bool(active and i['permit'] and complete)
        fire = bool(valid and i['ready'])
        cause = tval = 0
        if fault:
            if i['exception_valid']:
                cause, tval = i['exception_cause'], i['exception_tval']
            elif early or unknown:
                cause, tval = 2, i['original_instr'] & (0xFFFF if i['compressed'] else MASK)
            elif branch_bad:
                cause, tval = 0, target
            else:
                cause = 11 if machine else 8
        n_payload = active and not fault and bool(d['native'])
        x_payload = active and not fault and self.issued and self.accepted
        write = int(d['rd_we']) if n_payload else self.writeback if x_payload else 0
        rd = d['rd'] if n_payload else (i['instr'] >> 7) & 31 if x_payload and self.writeback else 0
        pair = bool(write & 2)
        pending = 0 if pair and rd == 0 else (write & 2) | int(bool(write & 1 and rd))
        resolve = bool(fire and not fault and native and d['branch'])
        o = dict(native=int(active and d['native']), rs_used=source_used, rs_need_now=need_now,
                 rs_ex_used=ex_used, rs_captured=source_used & i['rs_ready'],
                 valid=int(valid), ready=int(bool(i['rst_n'] and not i['flush'] and (not i['valid'] or fire))),
                 exception_valid=int(active and fault), exception_cause=cause if active else 0,
                 exception_tval=tval if active else 0,
                 serialize=int(active and (fault or d['native'] and d['serialize'])),
                 control_flow=int(bool(native and d['branch'])), branch_resolve=int(resolve),
                 branch_taken=int(resolve and taken), branch_target=target if native and d['branch'] else 0,
                 next_pc=i['pc'] if not active or fault else target if taken and not branch_bad else i['pc'] if branch_bad else sequential,
                 fu=d['fu'] if n_payload else 3, op=d['op'] if n_payload else 0,
                 a_sel=d['a_sel'] if n_payload else 2, b_sel=d['b_sel'] if n_payload else 2,
                 imm=d['imm'] if n_payload else 0,
                 a=(i['pc'] if d['a_sel'] == 1 else i['rs0'] if d['a_sel'] == 0 and i['rs_ready'] & 1 else 0) if n_payload else 0,
                 b=(d['imm'] if d['b_sel'] == 1 else i['rs1'] if d['b_sel'] == 0 and i['rs_ready'] & 2 else 0) if n_payload else 0,
                 c=i['rs2'] if n_payload and d['rs_used'] & 4 and i['rs_ready'] & 4 else 0,
                 rm=rm if n_payload else 0, pass_data=sequential if n_payload and d['pass_link'] and not branch_bad else 0,
                 store_data=i['rs1'] if n_payload and d['mem_we'] and i['rs_ready'] & 2 else 0,
                 rd_we=write & 1, rd=rd, rd1=(rd+1) & 31 if pair else 0, rd_pending=pending,
                 lsu=int(n_payload and d['lsu']), mem_we=int(n_payload and d['mem_we']),
                 mem_op=d['mem_op'] if n_payload else 0, wb_kind=d['wb_kind'] if n_payload else 3 if x_payload else 0,
                 system=d['system'] if n_payload else 0, csr_addr=d['csr_addr'] if n_payload else 0,
                 csr_op=d['csr_op'] if n_payload else 0,
                 csr_src=(d['imm'] if d['csr_imm'] else i['rs0'] if i['rs_ready'] & 1 else 0) if n_payload and d['wb_kind'] == 1 else 0,
                 csr_src_zero=int(n_payload and d['wb_kind'] == 1 and not (i['instr'] >> 15) & 31))
        o.update({f'rs{n}_addr': address for n,address in enumerate(addresses)})
        request = bool(active and i['permit'] and offer and not self.issued and i['xif_id_valid'])
        packed = mask = 0
        for n in range(self.p['XIF_NUM_RS']):
            available = self.operands[n] is not None or i['rs_ready'] & (1 << n)
            if request and available:
                mask |= 1 << n
                address = (i['instr'] >> (15,20,7)[n]) & 31
                value = self.operands[n] if self.operands[n] is not None else i['rs'+str(n)] if address else 0
                packed |= value << (32*n)
        issued = bool(self.p['XIF'] and i['rst_n'] and i['valid'] and self.issued)
        o.update(xif_issued=int(issued), xif_accepted=int(issued and self.accepted),
                 xif_cleanup_valid=int(cleanup), xif_cleanup_id=i['xif_id'] if cleanup else 0,
                 xif_issue_valid=int(request), xif_issue_instr=i['instr'] if request else 0,
                 xif_issue_hartid=i['hart_id'] if request else 0, xif_issue_id=i['xif_id'] if request else 0,
                 xif_register_valid=int(request), xif_register_hartid=i['hart_id'] if request else 0,
                 xif_register_id=i['xif_id'] if request else 0, xif_register_rs=packed,
                 xif_register_rs_valid=mask)
        return o

    def edge(self, i):
        o = self.evaluate(i)
        if not self.p['XIF']:
            return
        if not i['rst_n'] or i['flush'] or not i['valid'] or o['valid'] and i['ready']:
            self.clear()
            return
        if o['xif_issue_valid']:
            for n in range(self.p['XIF_NUM_RS']):
                address = (i['instr'] >> (15,20,7)[n]) & 31
                if self.operands[n] is None and i['rs_ready'] & (1 << n):
                    self.operands[n] = i['rs'+str(n)] if address else 0
            if i['xif_issue_ready']:
                self.issued = True
                self.accepted = bool(i['xif_issue_accept'])
                self.writeback = i['xif_issue_writeback']
                requested = i['xif_issue_register_read']
                bad_read = any(requested & (1 << n) and ((i['instr'] >> (15,20,7)[n]) & 31) >= 16 for n in range(self.p['XIF_NUM_RS']))
                rd = (i['instr'] >> 7) & 31
                self.bad = bool(self.accepted and (
                    requested & ~o['xif_register_rs_valid'] or self.p['ISA_E'] and (bad_read or self.writeback and rd >= 16) or self.writeback & 2 and rd % 2))
        if o['xif_cleanup_valid'] and i['xif_cleanup_ready']:
            self.cleaned = True
