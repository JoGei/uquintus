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
        return int(getattr(self.dut, name).value)

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
        if rst:
            if o['wb_retire']:
                self.retire(o['wb_pc_q'], o['wb_original_q'], o['wb_we0'], o['wb_waddr0'], o['wb_wdata0'])
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
