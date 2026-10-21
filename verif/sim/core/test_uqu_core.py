"""Native full-core programs, checked at retirement rather than by cycle counts."""
import cocotb
from pyuvm import uvm_root

from core_env import (CoreTest, BOOT, HANDLER, MASK, ins_i, ins_r, ins_s, ins_b,
                      ins_j, csr)


class IntegerTest(CoreTest):
    async def run_phase(self):
        self.raise_objection()
        program = [0x10500073]  # WFI follows the baseline no-op policy.
        program += [ins_i(r,0,self.rng.randrange(-2048,2048)) for r in range(1,16)]
        program += [0x812342b7, 0x00000317]  # LUI and AUIPC
        for n in range(240):
            a,b,rd = [self.rng.randrange(16) for _ in range(3)]
            f = n % 8
            if n % 3:
                program.append(ins_r(rd,a,b,f,32 if f in (0,5) and n%2 else 0))
            else:
                imm = self.rng.randrange(-2048,2048)
                if f in (1,5):
                    imm = self.rng.randrange(32) | (0x400 if f==5 and n%2 else 0)
                program.append(ins_i(rd,a,imm,f))
        # Consecutive youngest writers, store-independent EX consumers and DE branches.
        program += [ins_i(1,0,1),ins_i(1,1,2),ins_i(1,1,3),ins_r(2,1,1),
                    ins_b(1,1,8),ins_i(2,0,99),ins_i(3,0,4),ins_i(3,3,-1),
                    ins_b(3,0,-4,1),ins_j(4,8),ins_s(0,1),ins_i(5,4,17),
                    ins_i(0,5,0,0,0x67),ins_s(0,1),ins_i(6,0,11)]
        # JALR base is link PC+17; bit zero clears, target skips the poison store.
        end = self.put(BOOT,program)-4
        self.put(end+4,[ins_j(0,0)])
        await self.reset()
        await self.finish(end)
        assert not self.faults and not self.accesses
        self.drop_objection()


class MemoryTest(CoreTest):
    async def run_phase(self):
        self.raise_objection()
        self.data(0x4000,0x80fe7f01)
        program = [0x000040b7,ins_i(2,0,-86)]
        for f in (0,4,1,5,2):
            offsets = range(4) if f in (0,4) else (0,2) if f in (1,5) else (0,)
            for offset in offsets:
                program += [ins_i(3,1,offset,f,3),ins_r(4,3,3),ins_s(1,4,16),
                            ins_i(5,1,16,2,3),ins_b(4,5,8),ins_s(0,2)]
        for f,offset in ((0,1),(0,3),(1,2),(2,0)):
            program += [ins_s(1,2,offset,f),ins_i(6,1,0,2,3)]
        program += [ins_i(7,1,0,2,3),ins_i(8,1,16,2,3),ins_r(9,7,8),
                    ins_s(1,9,20),0x0ff0000f,ins_i(10,1,20,2,3)]
        if self.params['ISA_ZIFENCEI']:
            program += [0x0000100f]
        end = self.put(BOOT,program)-4
        self.put(end+4,[ins_j(0,0)])
        await self.reset()
        await self.finish(end)
        assert not self.accesses and not self.faults
        assert self.fences == ['fence'] + (['fencei'] if self.params['ISA_ZIFENCEI'] else [])
        self.drop_objection()


class TrapsTest(CoreTest):
    async def run_phase(self):
        self.raise_objection()
        self.skip_handler()
        program = self.setup_traps()+[0x000040b7,ins_i(2,0,77)]
        bad = [(ins_i(3,1,1,2,3),4,0x4001), (ins_s(1,2,2),6,0x4002),
               (0xffffffff,2,0xffffffff), (0x00000073,11,0), (0x00100073,3,0),
               (csr(0xfff,rd=3,f=2),2,None),
               (ins_i(3,1,0,2,3),5,0x4000), (ins_s(1,2,0),7,0x4000)]
        if not self.params['ISA_M']:
            bad += [(ins_r(3,1,2,0,1),2,None)]
        if self.params['ISA_E']:
            bad += [(ins_i(16,0,1),2,None),(ins_r(3,16,2),2,None)]
        if not self.params['ISA_C']:
            bad += [(ins_j(0,2),0,'target')]
        for instr,cause,tval in bad:
            pc = BOOT+4*len(program)
            self.expected_faults[pc] = cause, instr if tval is None else pc+2 if tval=='target' else tval
            program += [instr,ins_i(4,0,len(program))]
        end = self.put(BOOT,program)-4
        self.put(end+4,[ins_j(0,0)])
        self.errors['dmem'].add(0x4000)
        await self.reset()
        await self.finish(end)
        assert len(self.faults)==len(bad)
        assert self.word(self.memory,0x4000)==0, 'faulting store changed memory'
        # Access-fault requests complete with error but never retire.
        assert len(self.accesses)==2
        self.drop_objection()


class PreciseTest(CoreTest):
    async def run_phase(self):
        self.raise_objection()
        self.skip_handler()
        program = self.setup_traps()+[0x000040b7,ins_i(2,0,77)]
        # WB-only CSR legality must prevent a following store from escaping.
        fault_pc = BOOT+4*len(program)
        illegal = csr(0xfff,rd=3,f=2)
        self.expected_faults[fault_pc] = 2,illegal
        program += [illegal,ins_s(1,2),ins_i(4,0,9)]
        end = self.put(BOOT,program)-4
        self.put(end+4,[ins_j(0,0)])
        await self.reset()
        await self.until(lambda o:o['wb_exception_fire'])
        assert not self.accesses and not self.memory, 'younger store escaped before WB fault'
        await self.finish(end)
        assert self.word(self.memory,0x4000)==77
        # New reset image: an instruction access fault redirects into the handler,
        # which resumes at the following word; no failing bits become an opcode.
        self.expected_faults.clear()
        self.errors['imem'].add(0x2000)
        self.put(BOOT,self.setup_traps()+[0x000020b7,ins_i(0,1,0,0,0x67)])
        self.put(0x2000,[ins_s(0,2),ins_i(6,0,37),ins_j(0,0)])
        self.expected_faults[0x2000] = 1,0x2000
        await self.reset()
        await self.finish(0x2004)
        assert self.regs[6]==37
        self.drop_objection()


class PmpTest(CoreTest):
    async def run_phase(self):
        self.raise_objection()
        if self.params['ISA_PMP']:
            self.skip_handler()
            self.csrs.update({0x3a0:0,0x3b0:0})
            program = self.setup_traps()+[0x000010b7,csr(0x3b0,rs=1),ins_i(1,0,15),csr(0x3a0,rs=1)]
            if self.params['ISA_UMODE']:
                # MPRV makes M-mode LSU accesses use U permissions; IF stays M.
                program += [0x000200b7,csr(0x300,rs=1),0x000040b7,ins_i(2,0,7)]
                self.expected_faults[BOOT+4*len(program)] = 5,0x4000
                program += [ins_i(3,1,0,2,3)]
                self.expected_faults[BOOT+4*len(program)] = 7,0x4000
                program += [ins_s(1,2)]
            end = self.put(BOOT,program+[ins_i(5,0,39)])-4
            self.put(end+4,[ins_j(0,0)])
            await self.reset()
            await self.finish(end)
            assert not self.accesses and self.regs[5]==39
        else:
            # Disabled PMP CSR probing is legal: reads are zero, writes ignored.
            self.csrs[0x3a0] = 0
            self.put(BOOT,[ins_i(1,0,-1),csr(0x3a0,rs=1),csr(0x3a0,rd=3,f=2),
                           ins_i(5,0,39),ins_j(0,0)])
            await self.reset()
            await self.finish(BOOT+12)
            assert self.regs[3]==0 and not self.faults
        self.drop_objection()


class PrivilegeTest(CoreTest):
    async def run_phase(self):
        self.raise_objection()
        self.skip_handler()
        # Enter U through serialized MRET, then trap on privileged CSR access.
        if self.params['ISA_UMODE']:
            program = self.setup_traps()
            if self.params['ISA_PMP']:
                # Entry 0 TOR [0,0x8000), RWX, permits user code and handler.
                program += [0x000020b7,csr(0x3b0,rs=1),ins_i(1,0,15),csr(0x3a0,rs=1)]
                self.csrs.update({0x3b0:0,0x3a0:0})
            program += [0x000020b7,csr(0x341,rs=1),csr(0x300,rs=0),0x30200073]
            self.put(BOOT,program)
            self.put(0x2000,[ins_i(3,0,17),csr(0x300,rd=4,f=2),ins_i(5,3,2),ins_j(0,0)])
            self.expected_faults[0x2004] = 2,csr(0x300,rd=4,f=2)
            await self.reset()
            await self.finish(0x2008)
            assert self.regs[5]==19 and len(self.faults)==1 and not self.priv
        else:
            self.put(BOOT,self.setup_traps()+[csr(0x300,rd=3,f=2),csr(0x300,rs=0),csr(0x300,rd=4,f=2)])
            await self.reset()
            await self.finish(BOOT+20)
            assert self.regs[3] & 0x1800 == self.regs[4] & 0x1800 == 0x1800
        self.drop_objection()


class InterruptsTest(CoreTest):
    async def run_phase(self):
        self.raise_objection()
        # Vectored external interrupt, return to the exact interrupted boundary.
        program = self.setup_traps()+[ins_i(1,1,1),csr(0x305,rs=1),ins_i(1,0,-2048),
                    csr(0x304,rs=1),csr(0x300,rs=8,f=6),0x000040b7]
        program += [ins_i(2,1,0,2,3),ins_i(3,2,1),ins_s(1,3,4),ins_j(0,-12)]
        self.put(BOOT,program)
        self.data(0x4000,0x12345678)
        vector = HANDLER+44
        self.put(vector,[csr(0x342,rd=10,f=2),csr(0x341,rd=11,f=2),0x30200073])
        await self.reset()
        await self.until(lambda o: o['mie'] & 2048 and o['mstatus'] & 8 and self.pending['dmem'] is not None)
        await self.until(lambda o:o['trap_valid'],irq=2048)
        assert self.traps[-1][1]==11
        saved = self.traps[-1][0]
        await self.finish(vector+8)
        await self.until(lambda o:o['wb_retire'] and o['wb_pc_q']==saved)
        assert self.regs[10]==0x8000000b and self.regs[11]==saved and not self.faults
        self.drop_objection()


class ExtensionsTest(CoreTest):
    async def run_phase(self):
        self.raise_objection()
        program = [ins_i(r,0,r) for r in range(1,16)]
        if self.params['ISA_M']:
            for a,b in ((-29,7),(-1,0),(-1,-1),(0,17)):
                program += [ins_i(1,0,a),ins_i(2,0,b)]
                for op in range(8):
                    program += [ins_r(3,1,2,op,1),ins_r(4,3,3)]
            program += [0x800000b7,ins_i(2,0,-1)]
            program += [ins_r(3,1,2,op,1) for op in range(8)]
        if self.params['ISA_C']:
            # Place 32-bit instructions across word boundaries; original bits
            # and link length are checked by the retirement oracle.
            program += [(0x0085,2),ins_i(2,1,3),(0x9106,2),(0x9006,2),
                        (0x0085,2),ins_i(3,1,7),(0x0001,2),(0xa019,2),ins_s(0,1)]
        end = self.put(BOOT,program)
        self.put(end,[ins_i(7,0,123),ins_j(0,0)])
        await self.reset()
        await self.finish(end)
        assert self.regs[7]==123 and not self.faults
        self.drop_objection()


class ResetTest(CoreTest):
    async def run_phase(self):
        self.raise_objection()
        self.put(BOOT,[0x000040b7,ins_i(2,1,0,2,3),ins_s(1,2,4),ins_j(0,0)])
        self.put(0x2000,[ins_i(1,0,31),ins_i(2,1,11),ins_j(0,0)])
        self.data(0x4000,99)
        await self.reset()
        await self.until(lambda o:self.pending['dmem'] is not None)
        await self.reset(0x2000)
        await self.finish(0x2004)
        assert self.regs[2]==42 and self.word(self.memory,0x4004)==0
        self.drop_objection()


@cocotb.test(timeout_time=2000,timeout_unit='us')
async def integer(dut):
    await uvm_root().run_test('IntegerTest')

@cocotb.test(timeout_time=2000,timeout_unit='us')
async def memory(dut):
    await uvm_root().run_test('MemoryTest')

@cocotb.test(timeout_time=2000,timeout_unit='us')
async def traps(dut):
    await uvm_root().run_test('TrapsTest')

@cocotb.test(timeout_time=2000,timeout_unit='us')
async def precise(dut):
    await uvm_root().run_test('PreciseTest')

@cocotb.test(timeout_time=2000,timeout_unit='us')
async def pmp(dut):
    await uvm_root().run_test('PmpTest')

@cocotb.test(timeout_time=2000,timeout_unit='us')
async def privilege(dut):
    await uvm_root().run_test('PrivilegeTest')

@cocotb.test(timeout_time=2000,timeout_unit='us')
async def interrupts(dut):
    await uvm_root().run_test('InterruptsTest')

@cocotb.test(timeout_time=2000,timeout_unit='us')
async def extensions(dut):
    await uvm_root().run_test('ExtensionsTest')

@cocotb.test(timeout_time=2000,timeout_unit='us')
async def reset(dut):
    await uvm_root().run_test('ResetTest')
