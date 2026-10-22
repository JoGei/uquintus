"""ELF execution using the native core's existing pyuvm/RVFI environment."""
import json
import os
from pathlib import Path
import sys

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.core_env import CoreTest, MASK
from elf_image import completion_code, expected_traps, load_elf, validate_trap_sequence
from interrupts import interrupt_plan, InterruptStimulus
from benchmark_measure import BenchmarkWindow, coremark_result, read_log
from bpu_stats import unpack_snapshot, statistics as bpu_statistics


class ELFTest(CoreTest):
    def build_phase(self):
        super().build_phase()
        self.image = load_elf(os.environ['UQU_ELF'])
        self.image.validate_core(self.params)
        self.tohost = self.image.tohost
        self.expected_trap_events = expected_traps(self.image)
        self.expected_faults = {pc: (cause, tval) for pc, cause, tval in self.expected_trap_events}
        self.interrupts = InterruptStimulus(interrupt_plan(self.image,self.params))
        # Both independent OBI agents see the same RAM. The oracle owns a
        # separate copy, updated only by architectural stores at retirement.
        self.memory = self.image.memory()
        self.code = self.memory
        self.model_memory = dict(self.memory)
        self.model_code = self.model_memory
        self.exit_code = None
        self.last_retired = None
        self.max_cycles = int(os.environ['UQU_MAX_CYCLES'])
        self.benchmark = json.loads(os.environ.get('UQU_BENCHMARK', 'null'))
        self.window = BenchmarkWindow(self.image) if self.benchmark else None
        self.bpu_start = self.bpu_stop = None
        self.benchmark_evidence = dict(schema_version=1, status='running', mode='checked')

    async def cycle(self, **kwargs):
        if kwargs.get('rst',1) and not self.interrupts.lines and self.interrupts.index < len(self.interrupts.plan):
            trigger=self.interrupts.plan[self.interrupts.index]
            kind,pc=trigger['kind'],trigger['pc']
            retired=bool(self.retired and self.retired[-1]==pc)
            pending=bool(self.pending['dmem'] is not None and self.accesses and self.accesses[-1][0]==pc)
            arithmetic=bool(self.signal('ex_valid_q') and self.signal('ex_pc_q')==pc and
                            int(self.core.u_ex.issued_q.value) and not self.signal('ex_complete'))
            if {1:retired,2:pending,3:arithmetic}[kind]:
                self.interrupts.assert_next(self.cycles,self.rvfi_order,
                    dict(retired_pc=self.last_retired,dmem_pending=pending,multicycle_active=arithmetic,
                         priv_m=self.priv,mstatus=self.csrs[0x300],mie=self.csrs[0x304]))
        kwargs['irq']=self.interrupts.lines if kwargs.get('rst',1) else 0
        before = len(self.faults)
        before_irq=len(self.traps)
        result = await super().cycle(**kwargs)
        if len(self.faults) != before:
            validate_trap_sequence(self.expected_trap_events, self.faults)
        if len(self.traps)!=before_irq:
            self.interrupts.accept(*self.traps[-1],self.cycles-1,self.rvfi_order)
        return result

    def retire(self, pc, original, write, rd_actual, data_actual):
        # Keep all existing independent instruction/CSR and RVFI checks active.
        before = self.word(self.model_memory, self.tohost, 8)
        super().retire(pc, original, write, rd_actual, data_actual)
        if self.window:
            self.window.retire(pc, self.cycles, len(self.retired), data_actual,
                               self.csr_observer.model.words[0x320] & 5)
            if pc in (self.window.start_pc, self.window.stop_pc):
                values = unpack_snapshot(self.signal('bpu_counters_o'))
                if pc == self.window.start_pc:
                    self.bpu_start = values
                else:
                    self.bpu_stop = values
        self.last_retired = pc
        value = self.word(self.model_memory, self.tohost, 8)
        if value != before:
            record = self.rvfi_records[-1]
            assert record['mem_addr'] == self.tohost and record['mem_wmask'] == 15, (
                'tohost completion requires an aligned 32-bit store to its low word', record)
            assert value <= MASK, 'tohost upper word must remain zero'
            self.exit_code = completion_code(value)

    async def run_phase(self):
        self.raise_objection()
        status, detail = 'failed', None
        try:
            await self.reset(boot=self.image.entry)
            start = self.cycles
            while self.exit_code is None and self.cycles - start < self.max_cycles:
                await self.cycle()
            if self.exit_code is None:
                raise AssertionError(
                    f'ELF watchdog expired after {self.max_cycles} cycles; '
                    f'next PC={self.pc:08x}, last retired={self.last_retired}, '
                    f'instructions={len(self.retired)}; see rvfi.jsonl')
            assert self.exit_code == 0, f'ELF reported failure code {self.exit_code}; see rvfi.jsonl'
            validate_trap_sequence(self.expected_trap_events, self.faults, complete=True)
            self.interrupts.finish()
            assert not self.accesses, 'uncompleted memory operations'
            # RAM is modified when a store reaches the bus. Comparing the two
            # complete sparse images catches any flushed/faulting store effect,
            # including one that never produces an RVFI retirement record.
            assert self.memory == self.model_memory, 'unretired store modified shared RAM'
            if self.window:
                window = self.window.finish()
                bpu = bpu_statistics(self.bpu_start, self.bpu_stop, self.params, window['retired'])
                Path('bpu-stats.json').write_text(json.dumps(bpu, indent=2)+'\n')
                log = read_log(self.image, self.model_memory)
                Path('benchmark.log').write_text(log)
                assert self.benchmark['validator'] == 'coremark', 'unsupported benchmark validator'
                result = coremark_result(log, self.benchmark['profile'],
                                        self.benchmark['iterations'], window['cycles'])
                self.benchmark_evidence.update(window=window, result=result, bpu_statistics=bpu,
                                               memory=self.memory_timing)
            status = 'passed'
        except BaseException as error:
            detail = str(error)
            raise
        finally:
            # Flush the last accepted event even if its Python checker failed
            # before the normal falling edge. The SV sink flushes each record.
            self.dut.clk_i.value = 0
            await Timer(1, units='ns')
            Path('execution.json').write_text(json.dumps({
                'status': status, 'detail': detail, 'exit_code': self.exit_code,
                'cycles': self.cycles, 'retired': len(self.retired),
                'entry': self.image.entry, 'tohost': self.tohost,
                'next_pc': self.pc, 'last_retired_pc': self.last_retired,
                'max_cycles': self.max_cycles,
                'expected_traps': self.expected_trap_events, 'observed_traps': self.faults,
                'interrupts': self.interrupts.evidence(),
            }, indent=2) + '\n')
            Path('interrupts.json').write_text(json.dumps(self.interrupts.evidence(),indent=2)+'\n')
            self.timing['status'] = status
            Path('timing.json').write_text(json.dumps(self.timing,indent=2)+'\n')
            if self.window:
                self.benchmark_evidence.update(status=status, detail=detail)
                # Preserve partial windows and RAM output on watchdog/check failures.
                self.benchmark_evidence.update(start=self.window.start, stop=self.window.stop)
                Path('benchmark.json').write_text(json.dumps(self.benchmark_evidence, indent=2)+'\n')
                if not Path('benchmark.log').exists():
                    try:
                        Path('benchmark.log').write_text(read_log(self.image, self.model_memory))
                    except ValueError:
                        pass
            self.drop_objection()


@cocotb.test()
async def execute(dut):
    await uvm_root().run_test('ELFTest')
