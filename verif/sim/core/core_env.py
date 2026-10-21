"""Two independent native memory agents and a retirement instruction oracle."""
import json
import os
import random
import sys
from pathlib import Path

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_test

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from compressed_model import compressed
from rv32_arithmetic import alu_result, muldiv_result, signed
from rvfi_trace import read_trace
from rvfi_csrs import CSR_CATALOG, CSRObservation
from csregfile_model import INPUTS

MASK = 0xffffffff
BOOT = 0x1000
HANDLER = 0x1800


def ins_i(rd, rs, imm, f=0, opcode=0x13):
    return (imm & 4095) << 20 | rs << 15 | f << 12 | rd << 7 | opcode


def ins_r(rd, a, b, f=0, upper=0):
    return upper << 25 | b << 20 | a << 15 | f << 12 | rd << 7 | 0x33


def ins_s(base, data, imm=0, f=2):
    imm &= 4095
    return (imm >> 5) << 25 | data << 20 | base << 15 | f << 12 | (imm & 31) << 7 | 0x23


def ins_b(a, b, imm, f=0):
    imm &= 8191
    return ((imm >> 12) << 31 | ((imm >> 5) & 63) << 25 | b << 20 | a << 15 |
            f << 12 | ((imm >> 1) & 15) << 8 | ((imm >> 11) & 1) << 7 | 0x63)


def ins_j(rd, imm):
    imm &= 0x1fffff
    return ((imm >> 20) << 31 | ((imm >> 1) & 1023) << 21 | ((imm >> 11) & 1) << 20 |
            ((imm >> 12) & 255) << 12 | rd << 7 | 0x6f)


def csr(addr, rd=0, rs=0, f=1):
    return addr << 20 | rs << 15 | f << 12 | rd << 7 | 0x73


def sext(value, bits):
    return value - (1 << bits) if value >> (bits-1) else value


class CoreTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.core = self.dut.u_core
        self.params = json.loads(os.environ['UQU_COMPONENT_PARAMS'])
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))
        self.code = {}
        self.memory = {}
        self.model_memory = {}
        self.errors = {'imem': set(), 'dmem': set()}
        self.pending = dict(imem=None, dmem=None)
        self.held = dict(imem=None, dmem=None)
        self.accesses = []
        self.retired = []
        self.faults = []
        self.traps = []
        self.fences = []
        self.expected_faults = {}
        self.csr_overrides = {}
        self.regs = [0] + [None]*31
        self.pc = BOOT
        self.priv = 1
        self.csrs = {0x300: 0x1800, 0x304: 0, 0x305: 0, 0x340: 0,
                     0x341: 0, 0x342: 0, 0x343: 0, 0xf14: 5}
        self.cycles = 0
        self.random_wait = True
        self.rvfi_order = 0
        self.rvfi_entry = False
        self.rvfi_records = []
        self.csr_observer = CSRObservation(self.params)
        self.csr_records = []

    def put(self, addr, values):
        for entry in values:
            value, size = entry if isinstance(entry, tuple) else (entry, 4)
            for n in range(size):
                self.code[(addr+n)&MASK] = value >> (8*n) & 255
            addr = (addr+size)&MASK
        return addr

    def data(self, addr, value, size=4):
        for n in range(size):
            self.memory[addr+n] = self.model_memory[addr+n] = value >> (8*n) & 255

    @staticmethod
    def word(memory, addr, size=4):
        return sum(memory.get((addr+n)&MASK, 0) << (8*n) for n in range(size))

    def value(self, reg):
        assert self.regs[reg] is not None, f'oracle read uninitialized x{reg} at {self.pc:08x}'
        return self.regs[reg]

    def trap(self, pc, cause, tval, interrupt=False):
        status = self.csrs[0x300]
        self.csrs[0x300] = ((status & ~0x1888) | ((status & 8) << 4) | (0x1800 if self.priv else 0))
        self.csrs[0x341] = pc
        self.csrs[0x342] = cause | (0x80000000 if interrupt else 0)
        self.csrs[0x343] = tval
        self.priv = 1
        vector = self.csrs[0x305]
        self.pc = ((vector & ~3) + (4*cause if interrupt and vector & 1 else 0)) & MASK

    def retire(self, pc, original, write, rd_actual, data_actual):
        assert pc == self.pc, f'retirement PC {pc:08x}, expected {self.pc:08x}'
        raw = self.word(self.code, pc)
        size = 2 if self.params['ISA_C'] and raw & 3 != 3 else 4
        if size == 2:
            raw &= 65535
            decoded = compressed(raw)
            assert decoded is not None, f'reserved compressed retired: {raw:04x}'
            instr = decoded[1]
        else:
            instr = raw
        assert original == raw, f'original instruction lost at {pc:08x}: {original:08x} != {raw:08x}'
        assert pc not in self.expected_faults, f'faulting instruction retired at {pc:08x}'
        opcode, rd, f = instr & 127, (instr >> 7) & 31, (instr >> 12) & 7
        rs1, rs2, upper = (instr >> 15) & 31, (instr >> 20) & 31, instr >> 25
        imm = sext(instr >> 20, 12)
        result = None
        next_pc = (pc+size)&MASK
        if opcode == 0x37:
            result = instr & 0xfffff000
        elif opcode == 0x17:
            result = (pc+(instr & 0xfffff000))&MASK
        elif opcode in (0x13, 0x33):
            a = self.value(rs1)
            b = (imm & MASK) if opcode == 0x13 else self.value(rs2)
            if opcode == 0x33 and upper == 1:
                result = muldiv_result(f, a, b)
            else:
                op = f | (8 if (f == 5 or (opcode == 0x33 and f == 0)) and upper == 32 else 0)
                result = alu_result(op, a, b)
        elif opcode in (3, 0x23):
            offset = imm if opcode == 3 else sext(((instr >> 25) << 5) | ((instr >> 7)&31), 12)
            addr = (self.value(rs1)+offset)&MASK
            count = 1 << (f & 3)
            if opcode == 3:
                result = self.word(self.model_memory, addr, count)
                if f < 4:
                    result = sext(result, count*8)&MASK
            else:
                for n in range(count):
                    self.model_memory[addr+n] = self.value(rs2) >> (8*n) & 255
                result = None
            assert self.accesses, f'LSU retired without bus transaction at {pc:08x}'
            access = self.accesses.pop(0)
            assert access[:3] == (pc, int(opcode == 0x23), addr & ~3), (access, pc, addr)
            assert access[4] == ((1 << count)-1) << (addr & 3)
            if opcode == 0x23:
                lane_mask = ((1 << (count*8))-1) << ((addr & 3)*8)
                assert access[3] & lane_mask == (self.value(rs2) << ((addr & 3)*8)) & lane_mask
                assert self.word(self.memory, addr, count) == self.word(self.model_memory, addr, count)
        elif opcode == 0x63:
            a, b = self.value(rs1), self.value(rs2)
            taken = {0:a==b, 1:a!=b, 4:signed(a)<signed(b), 5:signed(a)>=signed(b), 6:a<b, 7:a>=b}[f]
            offset = sext(((instr >> 31) << 12) | (((instr >> 7)&1) << 11) | (((instr >> 25)&63) << 5) | (((instr >> 8)&15) << 1), 13)
            if taken:
                next_pc = (pc+offset)&MASK
        elif opcode == 0x6f:
            result = next_pc
            offset = sext(((instr >> 31) << 20) | (((instr >> 12)&255) << 12) | (((instr >> 20)&1) << 11) | (((instr >> 21)&1023) << 1), 21)
            next_pc = (pc+offset)&MASK
        elif opcode == 0x67:
            result = next_pc
            next_pc = (self.value(rs1)+imm)&MASK & ~1
        elif opcode == 0x73:
            if f:
                addr = instr >> 20
                assert addr in self.csrs or pc in self.csr_overrides, f'unmodeled CSR {addr:03x}'
                old = self.csr_overrides.get(pc, self.csrs.get(addr, 0))
                result = old
                source = rs1 if f & 4 else self.value(rs1)
                if (f & 3) == 1 or source:
                    new = source if (f & 3) == 1 else (old | source if (f & 3) == 2 else old & ~source)
                    if addr == 0x300:
                        new &= 0x221888
                        if not self.params['ISA_UMODE']:
                            new = new & ~0x218000 | 0x1800
                    if addr == 0x304:
                        new &= 0x888
                    if addr == 0x305:
                        new = new & ~3 | int((new & 3) == 1)
                    if not self.params['ISA_PMP'] and (0x3a0 <= addr <= 0x3a3 or 0x3b0 <= addr <= 0x3bf):
                        new = 0
                    self.csrs[addr] = new & MASK
            elif instr == 0x30200073:
                status = self.csrs[0x300]
                self.priv = int(not self.params['ISA_UMODE'] or (status & 0x1800) == 0x1800)
                self.csrs[0x300] = ((status & ~0x1888) | ((status >> 4) & 8) | 0x80 |
                                    (0 if self.params['ISA_UMODE'] else 0x1800))
                if not self.priv:
                    self.csrs[0x300] &= ~0x20000
                next_pc = self.csrs[0x341]
            else:
                assert instr == 0x10500073, f'unexpected system retirement: {instr:08x}'
        else:
            assert opcode == 0xf, f'unmodeled opcode {instr:08x}'
        expected_write = result is not None and rd != 0
        assert write == expected_write, f'write enable at {pc:08x} instr {instr:08x}: {write} != {expected_write}'
        if expected_write:
            assert (rd_actual, data_actual) == (rd, result), f'write at {pc:08x}: x{rd_actual}={data_actual:08x}, expected x{rd}={result:08x}'
            self.regs[rd] = result
        self.pc = next_pc
        self.retired.append(pc)

    def signal(self, name):
        owner = self.dut if hasattr(self.dut, name) else self.core
        return int(getattr(owner, name).value)

    def check_rvfi(self, o, rst):
        names = ('valid','order','insn','trap','halt','intr','mode','ixl',
            'rs1_addr','rs2_addr','rs1_rdata','rs2_rdata','rd_addr','rd_wdata',
            'pc_rdata','pc_wdata','mem_addr','mem_rmask','mem_wmask',
            'mem_rdata','mem_wdata','mem_fault','mem_fault_rmask','mem_fault_wmask')
        r = {n:self.signal('rvfi_'+n) for n in names}
        event = bool(rst and (o['wb_retire'] or o['wb_exception_fire']))
        assert r['valid'] == event, ('RVFI validity',r,o)
        if not rst:
            self.rvfi_order = 0
            self.rvfi_entry = False
            return r
        if event:
            assert r['order']==self.rvfi_order and r['ixl']==1 and not r['halt'], r
            assert r['intr']==self.rvfi_entry and r['mode']==(3 if self.priv else 0), r
            assert r['pc_rdata']==self.pc and r['trap']==o['wb_exception_fire'], r
            fetch_fault = bool(r['trap'] and o['wb_cause']==1)
            assert r['insn']==(0 if fetch_fault else o['wb_original_q']), r
            assert r['rd_addr']==(o['wb_waddr0'] if o['wb_we0'] else 0)
            assert r['rd_wdata']==(o['wb_wdata0'] if o['wb_we0'] else 0)
            raw = self.word(self.code,self.pc)
            instr = raw
            if self.params['ISA_C'] and raw & 3 != 3:
                decoded = compressed(raw & 65535)
                instr = decoded[1] if decoded else 0
            opcode, f = instr & 127, instr >> 12 & 7
            a,b,rd = instr >> 15 & 31, instr >> 20 & 31, instr >> 7 & 31
            uses_a = opcode in (0x13,0x33,3,0x23,0x63,0x67) or (opcode==0x73 and f in (1,2,3))
            uses_b = opcode in (0x33,0x23,0x63)
            illegal_e = self.params['ISA_E'] and ((uses_a and a>=16) or (uses_b and b>=16) or (opcode in (0x13,0x33,3,0x67) and rd>=16))
            unknown = fetch_fault or illegal_e or (opcode==0x33 and instr >> 25==1 and not self.params['ISA_M'])
            for n,addr,used in ((1,a,uses_a),(2,b,uses_b)):
                expected = addr if used and not unknown else 0
                assert r[f'rs{n}_addr']==expected, ('source address',r,hex(instr),expected)
                assert r[f'rs{n}_rdata']==(self.value(expected) if expected else 0), ('consumed operand',r,self.regs)
            memory = opcode in (3,0x23) and not unknown
            if memory:
                offset = sext(instr >> 20,12) if opcode==3 else sext(((instr >> 25) << 5) | ((instr >> 7)&31),12)
                addr = (self.value(a)+offset)&MASK
                mask = (((1 << (1 << (f & 3)))-1) << (addr & 3)) & 15
                assert r['mem_addr']==addr & ~3, r
                access_fault = bool(r['trap'] and o['wb_cause'] in (5,7))
                assert r['mem_fault']==access_fault, r
                for direction in ('r','w'):
                    match = (opcode==3) == (direction=='r')
                    assert r[f'mem_{direction}mask']==(mask if match and not r['trap'] else 0), r
                    assert r[f'mem_fault_{direction}mask']==(mask if match and access_fault else 0), r
                if not r['trap']:
                    lane_mask = sum(255 << (8*n) for n in range(4) if mask & (1 << n))
                    if opcode==3:
                        expected = self.word(self.model_memory,addr & ~3)
                        assert r['mem_rdata'] & lane_mask == expected & lane_mask, r
                    else:
                        expected = self.value(b) << ((addr & 3)*8)
                        assert r['mem_wdata'] & lane_mask == expected & lane_mask, r
            else:
                assert not any(r[n] for n in ('mem_rmask','mem_wmask','mem_fault_rmask','mem_fault_wmask')),r
                assert r['mem_fault']==fetch_fault,r
            self.rvfi_order += 1
            self.rvfi_entry = False
            self.rvfi_records.append(r)
        if o['trap_valid'] or o['wb_exception_fire']:
            self.rvfi_entry = True
        return r

    def check_phase(self):
        # The SV writer flushes on each clock edge. Check exactly the records
        # sampled by this test, including tests with multiple reset epochs.
        records = read_trace('rvfi.jsonl')
        instructions = [r for r in records if r['type']=='instruction']
        assert self.rvfi_records, 'test produced no architectural observations'
        actual = [{key:(1 if key=='valid' else r['rvfi_'+key]) for key in self.rvfi_records[0]}
                  for r in instructions[-len(self.rvfi_records):]]
        assert actual==self.rvfi_records, 'SV trace file differs from sampled RVFI'
        faults = [(r['rvfi_pc_rdata'],r['cause'],r['tval'])
                  for r in instructions[-len(self.rvfi_records):] if r['rvfi_trap']]
        assert faults==self.faults, 'trace trap diagnostics differ from expected faults'
        saved=[r['csrs'] for r in records if r['type'] in ('instruction','interrupt')]
        assert saved[-len(self.csr_records):]==self.csr_records, 'saved CSR observations differ from sampled channels'

    async def cycle(self, rst=1, grant=None, respond=None, irq=0, fence_ack=None):
        d = self.dut
        d.clk_i.value = 0
        d.rst_ni.value = rst
        d.irq_software_i.value = bool(irq & 8)
        d.irq_timer_i.value = bool(irq & 128)
        d.irq_external_i.value = bool(irq & 2048)
        ack = int(self.rng.randrange(4) == 0) if fence_ack is None else fence_ack
        d.fence_ack_i.value = d.fencei_ack_i.value = ack
        for bus in self.pending:
            getattr(d, bus+'_gnt_i').value = 0
            getattr(d, bus+'_rvalid_i').value = 0
            getattr(d, bus+'_rdata_i').value = self.rng.getrandbits(32)
            getattr(d, bus+'_err_i').value = 1
        await Timer(1, units='ns')
        grants, returns = {}, {}
        for bus in self.pending:
            req = self.signal(bus+'_req_o')
            fields = ('we','addr','wdata','be') if bus == 'dmem' else ('addr',)
            payload = tuple(self.signal(bus+'_'+f+'_o') for f in fields)
            if rst and self.held[bus] is not None:
                assert req and payload == self.held[bus], f'{bus} request changed before grant'
            take = rst and req and (self.rng.randrange(3)!=0 if grant is None and self.random_wait else (1 if grant is None else grant))
            pending = self.pending[bus]
            returning = rst and pending is not None and (pending[0] == 0 if respond is None else respond)
            grants[bus] = (take, payload)
            returns[bus] = returning
            getattr(d, bus+'_gnt_i').value = int(take)
            getattr(d, bus+'_rvalid_i').value = int(returning)
            if returning:
                getattr(d, bus+'_rdata_i').value = pending[1]
                getattr(d, bus+'_err_i').value = pending[2]
            self.held[bus] = payload if rst and req and not take else None
        await Timer(1, units='ns')
        o = {n:self.signal(n) for n in ('wb_retire','wb_exception_fire','wb_pc_q','wb_original_q',
                'wb_we0','wb_waddr0','wb_wdata0','wb_cause','wb_tval','trap_valid','trap_pc','trap_cause',
                'redirect_valid','redirect_addr','de_valid_q','ex_valid_q','mem_valid_q','wb_valid_q',
                'priv_m_q','mstatus','mie','mip','mtvec','mepc','de_pc_q','mem_pc_q')}
        ci = dict(INPUTS, rst_n=rst, priv_m=self.priv, hart_id=5,
            irq_software=int(bool(irq & 8)), irq_timer=int(bool(irq & 128)),
            irq_external=int(bool(irq & 2048)), retire=o['wb_retire'],
            trap=int(bool(o['trap_valid'] or o['wb_exception_fire'])),
            trap_pc=o['trap_pc'] if o['trap_valid'] else o['wb_pc_q'],
            trap_interrupt=o['trap_valid'],
            trap_cause=o['trap_cause'] if o['trap_valid'] else o['wb_cause'],
            trap_tval=0 if o['trap_valid'] else o['wb_tval'], mret=self.signal('wb_mret'))
        instr=o['wb_original_q']
        if rst and (o['wb_retire'] or o['wb_exception_fire']) and instr & 127==0x73 and (instr >> 12)&7:
            op=(instr >> 12)&7
            rs=(instr >> 15)&31
            ci.update(csr_valid=1, csr_commit=o['wb_retire'],csr_addr=instr >> 20,
                csr_op=op,csr_src=rs if op & 4 else self.value(rs),
                csr_src_zero=int(rs==0),csr_rd_zero=int((instr >> 7)&31==0),csr_instr=instr)
        expected_csrs=self.csr_observer.step(ci,bool(o['wb_retire'] or o['wb_exception_fire'] or o['trap_valid']))
        if o['wb_retire'] and ci['csr_valid']:
            self.csr_overrides[o['wb_pc_q']]=self.csr_observer.read_result
        if rst:
            for bus in self.pending:
                if returns[bus]:
                    self.pending[bus] = None
                elif self.pending[bus] is not None:
                    delay, data, err = self.pending[bus]
                    self.pending[bus] = max(0,delay-1), data, err
                take, payload = grants[bus]
                if take:
                    assert self.pending[bus] is None, f'{bus} multiple outstanding requests'
                    addr = payload[1] if bus == 'dmem' else payload[0]
                    assert addr & 3 == 0
                    error = addr in self.errors[bus]
                    memory = self.code if bus == 'imem' else self.memory
                    data = self.word(memory, addr)
                    if bus == 'dmem':
                        we, addr, value, be = payload
                        self.accesses.append((o['mem_pc_q'], *payload))
                        if we and not error:
                            for n in range(4):
                                if be & (1 << n):
                                    memory[addr+n] = value >> (8*n) & 255
                    delay = self.rng.randrange(8) if self.random_wait else 0
                    self.pending[bus] = delay, data, int(error)
            for name in ('fence','fencei'):
                if self.signal(name+'_req_o') and ack:
                    self.fences.append(name)
            assert not any(self.signal(n) for n in ('xif_issue_valid_o','xif_register_valid_o','xif_commit_valid_o','xif_result_ready_o'))
        else:
            self.pending = dict(imem=None,dmem=None)
        d.clk_i.value = 1
        await Timer(1, units='ns')
        rvfi = self.check_rvfi(o, rst)
        observed_csrs={}
        for name in CSR_CATALOG:
            values={field:self.signal('rvfi_csr_'+name+'_'+field) for field in ('rmask','wmask','rdata','wdata')}
            if values['rmask'] or values['wmask']: observed_csrs[name]=values
        assert observed_csrs==expected_csrs, ('CSR observation',o,observed_csrs,expected_csrs)
        if rst:
            if o['wb_retire']:
                self.retire(rvfi['pc_rdata'], rvfi['insn'], int(rvfi['rd_addr']!=0), rvfi['rd_addr'], rvfi['rd_wdata'])
            if o['wb_exception_fire']:
                assert not o['wb_retire'] and not o['wb_we0']
                assert o['wb_pc_q'] == self.pc
                expected = self.expected_faults.get(self.pc)
                assert expected is not None, f'unexpected fault PC={self.pc:08x}, cause={o["wb_cause"]}, tval={o["wb_tval"]:08x}'
                assert (o['wb_cause'], o['wb_tval']) == expected, (hex(self.pc),o['wb_cause'],hex(o['wb_tval']),expected)
                self.faults.append((self.pc, *expected))
                self.trap(self.pc, *expected)
            if o['trap_valid']:
                assert not o['wb_retire'] and not o['wb_exception_fire']
                assert o['trap_pc'] == self.pc, (o, self.pc)
                assert not any(o[n] for n in ('ex_valid_q','mem_valid_q','wb_valid_q'))
                self.traps.append((self.pc, o['trap_cause']))
                self.trap(self.pc, o['trap_cause'], 0, True)
            if o['wb_retire'] or o['wb_exception_fire']:
                assert self.signal('rvfi_pc_wdata')==self.pc, ('RVFI next PC',self.rvfi_records[-1],self.pc)
            if o['wb_retire'] or o['wb_exception_fire'] or o['trap_valid']:
                self.csr_records.append(observed_csrs)
            self.csrs.update(self.csr_observer.model.words)
        d.clk_i.value = 0
        await Timer(1, units='ns')
        self.cycles += 1
        return o

    async def reset(self, boot=BOOT):
        d = self.dut
        d.boot_addr_i.value = boot
        d.hart_id_i.value = 5
        for n in ('xif_issue_ready','xif_issue_accept','xif_issue_writeback','xif_issue_register_read',
                  'xif_register_ready','xif_result_valid','xif_result_hartid','xif_result_id',
                  'xif_result_data','xif_result_rd','xif_result_we'):
            getattr(d, n+'_i').value = 0
        self.pc = boot
        self.priv = 1
        self.csrs.update({0x300: 0x1800,
                         0x304:0, 0x305:0, 0x341:0, 0x342:0, 0x343:0, 0x340:0})
        self.accesses.clear()
        await self.cycle(rst=0)
        await self.cycle(rst=0)
        assert not any(self.signal(n) for n in ('de_valid_q','ex_valid_q','mem_valid_q','wb_valid_q'))

    async def until(self, predicate, limit=30000, **changes):
        for _ in range(limit):
            o = await self.cycle(**changes)
            if predicate(o):
                return o
        raise AssertionError(f'core timed out PC={self.pc:08x}, retired={len(self.retired)}; last={o}')

    async def finish(self, pc, **changes):
        await self.until(lambda o: pc in self.retired, **changes)

    def setup_traps(self):
        return [0x000020b7, ins_i(1,1,-2048), csr(0x305,rs=1)]  # mtvec=HANDLER

    def skip_handler(self):
        self.put(HANDLER, [csr(0x342,rd=10,f=2), csr(0x343,rd=11,f=2),
            csr(0x341,rd=12,f=2), ins_i(12,12,4), csr(0x341,rs=12), 0x30200073])
