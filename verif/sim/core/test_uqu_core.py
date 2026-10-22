"""Native full-core programs, checked at retirement rather than by cycle counts."""
import cocotb
from pyuvm import uvm_root

from core_env import (CoreTest, BOOT, HANDLER, MASK, ins_i, ins_r, ins_s, ins_b,
                      ins_j, csr)
from rvfi_csrs import CSR_CATALOG
from compressed_model import compressed


def custom_word(rd=6, a=1, b=2, op=0):
    return b << 20 | a << 15 | op << 12 | rd << 7 | 0x0b


class PredictionTest(CoreTest):
    async def cycle(self, *args, **kwargs):
        o = await super().cycle(*args, **kwargs)
        if o.get('predictor_invalidate'):
            self.predictor_invalidations += 1
        if o.get('de_fire') and not o['wb_exception_fire']:
            self.resolutions.append(dict(pc=o['de_pc_q'], taken=o['de_branch_taken'],
                predicted=o['de_predicted_next_pc_q'], actual=o['de_next_pc'],
                correction=o['de_redirect']))
        return o

    async def run_phase(self):
        self.raise_objection()
        self.resolutions = []
        self.predictor_invalidations = 0
        program = [ins_i(1,0,8), ins_i(2,0,0), ins_i(2,2,1), ins_i(1,1,-1),
                   ins_b(1,0,-8,1), ins_j(5,8), 0, ins_i(6,0,123)]
        branch_pc = BOOT + 16
        self.put(BOOT, program + [0x00001437, ins_i(8,8,0x400), ins_j(0,0x1200-(BOOT+40))])
        # The same indirect jump changes its target on the second visit.
        self.put(0x1200, [ins_i(5,8,0,0,0x67)])
        self.put(0x1400, [0x00001437, ins_i(8,8,0x500), ins_j(0,0x1200-0x1408)])
        if self.params['ISA_ZIFENCEI']:
            # Revisit the warmed indirect PC after FENCE.I. It must be cold,
            # rather than predict its old target, and then use the new operand.
            self.put(0x1500, [ins_i(7,0,77), 0x0000100f, 0x00001437,
                             ins_i(8,8,0x600), ins_j(0,0x1200-0x1510)])
        else:
            self.put(0x1500, [ins_i(7,0,77), ins_j(0,0x1600-0x1504)])
        finish_pc = 0x1600
        if self.params['ISA_C']:
            branch = ins_b(8,0,-2,1)
            cbranch = next(h for h in range(0xe001, 0x10000, 4)
                           if compressed(h) and compressed(h)[1] == branch)
            self.put(0x1600, [(ins_i(8,0,8),4), (0x147d,2), (cbranch,2),
                              (ins_i(9,0,99),4), (ins_j(0,0),4)])
            finish_pc = 0x1608
        else:
            self.put(0x1600, [ins_i(9,0,99), ins_j(0,0)])
        await self.reset()
        await self.finish(finish_pc)
        assert self.regs[2] == 8 and self.regs[6] == 123 and self.regs[7] == 77
        assert not self.faults and not self.accesses
        if self.params['MUA_BRANCH_PREDICTOR'] == 2 and self.params['MUA_BTB'] != 0:
            loop = [row for row in self.resolutions if row['pc'] == branch_pc]
            assert len(loop) == 8, loop
            assert loop[0]['correction'] and not loop[-1]['taken'] and loop[-1]['correction'], loop
            assert sum(row['taken'] and not row['correction'] for row in loop) >= 4, loop
            indirect = [row for row in self.resolutions if row['pc'] == 0x1200]
            assert len(indirect) == 2 + int(bool(self.params['ISA_ZIFENCEI'])), indirect
            assert indirect[1]['predicted'] == 0x1400, indirect
            assert indirect[1]['actual'] == 0x1500 and indirect[1]['correction'], indirect
            assert self.predictor_invalidations == int(bool(self.params['ISA_ZIFENCEI']))
            if self.params['ISA_ZIFENCEI']:
                assert indirect[2]['predicted'] == 0x1204 and indirect[2]['actual'] == 0x1600, indirect
            if self.params['ISA_C']:
                compact = [row for row in self.resolutions if row['pc'] == 0x1606]
                assert len(compact) == 8 and compact[-1]['correction'], compact
                assert sum(row['taken'] and not row['correction'] for row in compact) >= 4, compact
        self.drop_objection()


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def prediction(dut):
    await uvm_root().run_test('PredictionTest')


class HartIdTest(CoreTest):
    async def run_phase(self):
        self.raise_objection()
        self.skip_handler()
        program=self.setup_traps()+[csr(0xf14,rd=1,f=2),csr(0xf14,rd=2,f=6)]
        bad=csr(0xf14,rd=3,rs=1)
        self.expected_faults[BOOT+4*len(program)]=(2,bad)
        program += [bad,csr(0xf14,rd=4,f=2)]
        end=self.put(BOOT,program)
        self.put(end,[ins_j(0,0)])
        await self.reset()
        await self.finish(end)
        assert [self.regs[r] for r in (1,2,4)]==[self.hart_id]*3
        assert len(self.faults)==1
        assert not hasattr(self.dut,'hart_id_i')
        self.drop_objection()


@cocotb.test(timeout_time=100,timeout_unit='us')
async def hart_id(dut):
    await uvm_root().run_test('HartIdTest')


class XifTest(CoreTest):
    async def run_phase(self):
        self.raise_objection()
        if not self.coprocessor:
            self.put(BOOT,[ins_i(1,0,7),ins_j(0,0)])
            await self.reset()
            for name,value in dict(xif_issue_ready_i=1,xif_issue_accept_i=1,xif_issue_writeback_i=1,
                    xif_issue_register_read_i=(1 << self.params['XIF_NUM_RS'])-1,xif_register_ready_i=1,
                    xif_result_valid_i=1,xif_result_hartid_i=self.hart_id,xif_result_id_i=7,
                    xif_result_data_i=0xffffffff,xif_result_rd_i=1,xif_result_we_i=1).items():
                getattr(self.dut,name).value=value
            await self.finish(BOOT)
            self.drop_objection(); return
        agent=self.coprocessor
        agent.delay=120
        agent.bad_packets=3
        agent.same_cycle=True
        self.skip_handler()
        program=self.setup_traps()+[ins_i(r,0,r) for r in range(1,16)]
        rejected=BOOT+4*len(program)
        program += [0x0000005b,ins_i(1,0,7),ins_i(2,0,11)]
        self.expected_faults[rejected]=(2,0x5b)
        for rd in (8,10,12,14): program.append(custom_word(rd))
        program += [ins_r(5,8,10)]
        if self.params['XIF_NUM_RS']==3:
            program += [ins_i(6,0,3),custom_word(6,5,2,1),custom_word(7,0,0,5)]
        if self.params['XIF_DUALWRITE']:
            program += [custom_word(8,1,2,3),ins_r(4,9,8),custom_word(0,1,2,3)]
        program += [custom_word(31,31,31,2)]  # No used registers, also legal on E.
        end=self.put(BOOT,program)
        self.put(end,[ins_i(7,0,123),ins_j(0,0)])
        await self.reset(); await self.finish(end)
        assert agent.max_live==4,('offloads serialized',agent.max_live,agent.history)
        assert sum(r['type']=='invalid_result' for r in agent.history)==3
        assert any(r['type']=='kill' and r['pc']==rejected for r in agent.history)
        assert not agent.live

        # A late memory fault flushes accepted offloads in EX and DE. They are
        # killed, then reissued after the handler skips the faulting load.
        self.code.clear(); self.expected_faults.clear(); self.retired.clear()
        self.skip_handler(); agent.delay=3
        program=self.setup_traps()+[ins_i(r,0,r) for r in range(1,16)]+[0x000040b7]
        load=BOOT+4*len(program)
        program += [ins_i(4,1,0,2,3),custom_word(6,2,3),custom_word(8,2,3)]
        end=self.put(BOOT,program); self.put(end,[ins_i(7,0,124),ins_j(0,0)])
        self.data(0x4000,0x12345678); self.errors['dmem'].add(0x4000)
        self.expected_faults[load]=(5,0x4000)
        before=len(agent.history)
        await self.reset()
        await self.until(lambda o:len(agent.live)>=2,respond={'dmem':0})
        await self.finish(end)
        killed=[r for r in agent.history[before:] if r['type']=='kill']
        assert {r['pc'] for r in killed}=={load+4,load+8},killed
        assert not agent.live

        # An interrupt evicts only speculative DE; EX/MEM/WB must complete.
        self.code.clear(); self.expected_faults.clear(); self.retired.clear(); self.errors['dmem'].clear()
        self.put(HANDLER,[csr(0x342,rd=11,f=2),csr(0x341,rd=12,f=2),0x30200073])
        program=self.setup_traps()+[ins_i(r,0,r) for r in range(1,16)]
        program += [csr(0x304,rs=8,f=5),csr(0x300,rs=8,f=6)]
        first=BOOT+4*len(program)
        program += [custom_word(rd,2,3) for rd in (4,6,8,10)]
        end=self.put(BOOT,program); self.put(end,[ins_i(7,0,125),ins_j(0,0)])
        agent.hold_result=True
        before=len(agent.history)
        await self.reset()
        await self.until(lambda o:sum(r['accepted'] for r in agent.live)==4)
        for _ in range(5): await self.cycle(irq=8)
        assert not self.traps
        assert any(r['type']=='kill' and r['pc']==first+12 for r in agent.history[before:])
        agent.hold_result=False
        await self.until(lambda o:o['trap_valid'],irq=8)
        assert self.traps[-1]==(first+12,3),self.traps
        await self.finish(end)
        assert not agent.live
        # Shared reset discards unfinished coprocessor work and every pipeline
        # token, then restarts fresh issue without a stale completion/write.
        self.code.clear(); self.expected_faults.clear(); self.retired.clear()
        end=self.put(BOOT,[ins_i(1,0,9),ins_i(2,0,5),custom_word(6),ins_j(0,0)])
        agent.hold_result=True
        await self.reset()
        await self.until(lambda o:agent.live and o['wb_valid_q'] and self.signal('wb_kind_q')==3)
        assert agent.live and not any(r['pc']==BOOT+8 for r in agent.trace if r['epoch']==agent.epoch)
        self.code.clear(); self.retired.clear()
        end=self.put(BOOT,[ins_i(1,0,9),ins_i(2,0,5),custom_word(6)])
        self.put(end,[ins_i(7,0,127),ins_j(0,0)])
        await self.reset(); agent.hold_result=False
        await self.finish(end)
        assert self.regs[6]==14 and not agent.live
        if self.params['ISA_E']:
            # Contain an integration violation: RV32E-unaware acceptance of a
            # destination outside x0..x15 must be killed before illegal trapping.
            self.code.clear(); self.expected_faults.clear(); self.retired.clear()
            self.skip_handler()
            program=self.setup_traps()+[ins_i(1,0,7)]
            bad_pc=BOOT+4*len(program); bad=custom_word(16,1,0)
            program += [bad]
            end=self.put(BOOT,program); self.put(end,[ins_i(7,0,126),ins_j(0,0)])
            self.expected_faults[bad_pc]=(2,bad)
            agent.force_bad_accept=True
            before=len(agent.history)
            await self.reset(); await self.finish(end)
            assert any(r['type']=='kill' and r['pc']==bad_pc for r in agent.history[before:])
            assert not agent.live
        self.drop_objection()


class FpuTest(CoreTest):
    def setup_traps(self):
        # The operation/rounding matrix extends beyond the usual small image.
        return [0x000080b7,csr(0x305,rs=1)]

    def skip_handler(self):
        self.put(0x8000, [csr(0x342,rd=10,f=2),csr(0x343,rd=11,f=2),
            csr(0x341,rd=12,f=2),ins_i(12,12,4),csr(0x341,rs=12),0x30200073])

    async def run_phase(self):
        from fpu_model import encode_instruction as fp
        self.raise_objection()
        self.skip_handler()
        program = self.setup_traps()
        def constant(rd, value):
            high = ((value + 0x800) >> 12) & 0xfffff
            return [high << 12 | rd << 7 | 0x37, ins_i(rd, rd, value & 0xfff)]
        if self.params['ISA_ZFINX']:
            # Read-after-write dependencies cover all three operands and the
            # result; CSR serialization must observe only committed flags.
            for op in range(22):
                for rm in range(5):
                    program += constant(1, 0x3fc00000) + constant(2, 0x40400000) + constant(3, 0xbf800000)
                    program += [fp(op, 4, 1, 2, 3, rm), ins_r(5,4,4),
                                csr(1,rd=6,f=2),csr(3,rd=7,f=2)]
            for rm in range(5):
                program += [csr(2,rs=rm,f=5),fp(3,4,1,2,rm=7),csr(3,rd=7,f=2)]
            program += [csr(1,rs=0)] + constant(1,0x3f800000) + constant(2,0)
            program += [fp(3,0,1,2),csr(1,rd=6,f=2)]  # x0 still accrues DZ.
            flags_pc = BOOT + 4*(len(program)-1)
            program += constant(1,0xbf800000) + [fp(4,4,1),csr(1,rd=8,f=2)]
            # Reserved static and dynamic rounding modes trap before execution.
            for bad in (fp(0,4,1,2,rm=5),):
                self.expected_faults[BOOT+4*len(program)] = 2,bad
                program.append(bad)
            program += [csr(2,rs=7,f=5)]
            bad = fp(0,4,1,2,rm=7)
            self.expected_faults[BOOT+4*len(program)] = 2,bad
            program += [bad,csr(2,rs=0)]
        else:
            bad = fp(0,4,0,0)
            self.expected_faults[BOOT+4*len(program)] = 2,bad
            program.append(bad)
        end=self.put(BOOT,program)
        self.put(end,[ins_i(7,0,127),ins_j(0,0)])
        await self.reset()
        await self.finish(end)
        if self.params['ISA_ZFINX']:
            assert self.regs[6] == 8 and self.regs[8] == 24, 'x0/accumulated FP flags'
            assert flags_pc in self.retired
            assert {'fflags','frm','fcsr'} <= set().union(*(set(r) for r in self.csr_records))
            # An older fault must discard a younger FPU result and its flags.
            self.code.clear(); self.retired.clear(); self.expected_faults.clear()
            self.skip_handler()
            program=self.setup_traps()+constant(1,0x3f800000)+constant(2,0)+constant(3,0x4000)
            fault_pc=BOOT+4*len(program)
            program += [ins_i(5,3,0,2,3),fp(3,4,1,2),csr(1,rd=6,f=2)]
            end=self.put(BOOT,program); self.put(end,[ins_i(7,0,126),ins_j(0,0)])
            self.errors['dmem'].add(0x4000); self.expected_faults[fault_pc]=5,0x4000
            await self.reset()
            await self.until(lambda o:self.pending['dmem'] is not None,respond={'dmem':0})
            for _ in range(8): await self.cycle(respond={'dmem':0})
            assert self.signal('ex_valid_q'), 'FPU token did not wait behind older MEM'
            assert self.signal('wb_fflags_valid_q') == 0
            await self.finish(end)
            assert self.regs[6] == 8, 'reissued FPU must retire exactly once after the trap'
            # IRQ entry drains the executing FPU and its WB flag update.
            self.code.clear(); self.retired.clear(); self.expected_faults.clear()
            self.errors['dmem'].clear()
            self.put(0x8000,[csr(0x342,rd=10,f=2),csr(0x341,rd=11,f=2),
                             csr(1,rd=6,f=2),0x30200073])
            program=self.setup_traps()+constant(1,0x3f800000)+constant(2,0x40400000)
            program += [csr(0x304,rs=8,f=5),csr(0x300,rs=8,f=6)]
            operation_pc=BOOT+4*len(program)
            program += [fp(3,4,1,2)]
            end=self.put(BOOT,program); self.put(end,[ins_i(7,0,125),ins_j(0,0)])
            await self.reset()
            await self.until(lambda o:self.signal('ex_valid_q') and self.signal('ex_fu_q') == 2
                             and not self.signal('ex_complete'))
            entries=len(self.traps)
            for _ in range(3):
                await self.cycle(irq=8)
                assert len(self.traps)==entries, 'IRQ cancelled active FPU'
            await self.until(lambda o:o['trap_valid'],irq=8)
            assert operation_pc in self.retired and self.traps[-1] == (end,3), self.traps
            await self.finish(end)
            assert self.regs[6] == 1, 'IRQ handler missed retired inexact flag'
        self.drop_objection()


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


class CsrsTest(CoreTest):
    async def run_phase(self):
        self.raise_objection()
        self.skip_handler()
        program=self.setup_traps()+[ins_i(1,0,-1),csr(0x340,rd=2,rs=1),
            csr(0x340,rd=3,f=2),csr(0x340,rd=4,rs=31,f=7),
            csr(0x340,rd=5,rs=17,f=6),csr(0x340,rd=0,rs=7,f=5),
            ins_i(6,0,3),csr(0x340,rd=7,rs=6,f=2),csr(0x340,rd=8,rs=6,f=3),
            csr(0x301,rd=2,rs=1),csr(0x301,rd=3,f=2)]
        # WARL, ignored fixed fields, and explicit read/write suppression.
        for addr in (0x300,0x304,0x305,0x310,0x341,0x342,0x343,0x344):
            program += [csr(addr,rd=0,rs=1),csr(addr,rd=3,f=2)]
        program += self.setup_traps()  # Restore a usable vector before faults.
        if self.params['ISA_UMODE']:
            for addr in (0x306,0x30a,0x31a):
                program += [csr(addr,rs=1),csr(addr,rd=3,f=2)]
        # Freeze both counters; full 64-bit snapshots must preserve the other
        # half and aggregate machine high/user aliases into one channel.
        program += [csr(0x320,rs=5,f=5),ins_i(1,0,-1)]
        for addr in (0xb00,0xb80,0xb02,0xb82):
            program += [csr(addr,rs=1),csr(addr,rd=3,f=2)]
        program += [csr(a,rd=3,f=2) for a in (0xc00,0xc80,0xc02,0xc82)]
        # Counter increments are between RVFI instructions, not implicit CSR
        # writes on every event. Unfreeze and observe both live counters.
        program += [csr(0x320,rs=0),ins_i(1,0,19),csr(0xb00,rd=3,f=2),csr(0xb02,rd=4,f=2)]
        for n in range(16):
            program += [csr(0x3b0+n,rs=0),csr(0x3b0+n,rd=3,f=2)]
        for n in range(4):
            program += [csr(0x3a0+n,rs=0),csr(0x3a0+n,rd=3,f=2)]
        if self.params['ISA_PMP']:
            program += [0x000020b7,csr(0x3b0,rs=1),ins_i(1,0,0x8f),csr(0x3a0,rs=1),
                        ins_i(1,0,-1),csr(0x3b0,rs=1),csr(0x3b0,rd=3,f=2),
                        csr(0x3a0,rs=0),csr(0x3a0,rd=3,f=2)]
        if self.params['ISA_ZFINX']:
            for addr in (1, 2, 3):
                program += [csr(addr,rs=1),csr(addr,rd=3,f=2)]
        for addr in (0xf11,0xf12,0xf13,0xf14,0xf15):
            program += [csr(addr,rd=3,f=2)]
        for n in range(3,32):
            # All hardwired HPM counters/events remain legal zero-valued CSRs.
            program += [csr(0xb00+n,rs=1),csr(0xb80+n,rd=3,f=2),
                        csr(0xc00+n,rd=3,f=2),csr(0xc80+n,rd=3,f=2),
                        csr(0x320+n,rs=1),csr(0x320+n,rd=3,f=2)]
        bad=csr(0xf14,rd=3,rs=1)
        self.expected_faults[BOOT+4*len(program)]=2,bad
        program += [bad,ins_i(7,0,91)]
        end=self.put(BOOT,program)-4
        self.put(end+4,[ins_j(0,0)])
        await self.reset()
        await self.finish(end)
        assert len(self.faults)==1 and self.regs[7]==91
        expected=set(CSR_CATALOG)
        if not self.params['ISA_ZFINX']:
            expected -= {'fflags','frm','fcsr'}
        if not self.params['ISA_UMODE']:
            expected -= {'mcounteren','menvcfg','menvcfgh'}
        assert set().union(*(set(r) for r in self.csr_records))==expected, 'CSR suite did not exercise every available channel'
        self.drop_objection()


@cocotb.test(timeout_time=2000,timeout_unit='us')
async def csrs(dut):
    await uvm_root().run_test('CsrsTest')


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

@cocotb.test(timeout_time=2000,timeout_unit='us')
async def xif(dut):
    await uvm_root().run_test('XifTest')


@cocotb.test(timeout_time=2000,timeout_unit='us')
async def fpu(dut):
    await uvm_root().run_test('FpuTest')
