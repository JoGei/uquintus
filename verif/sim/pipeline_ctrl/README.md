# Core pipeline controller

[uqu_pipeline_ctrl.v](../../../src/uquintus/uqu_pipeline_ctrl.v) controls movement,
age-based fault containment, serialization, machine interrupt draining, memory
effects, redirects and fence completion. Its only hardware parameter is
`ISA_ZIFENCEI` (default 0). It owns two fence-handshake bits; it owns no pipeline
registers, instruction-valid bits, instruction payload, privilege, CSR state,
operand storage, memory state machines or XIF IDs.

```sh
make test COMPONENT=pipeline_ctrl CONFIG=rv32i
make test COMPONENT=pipeline_ctrl CONFIG=rv32i_zifencei
make test COMPONENT=pipeline_ctrl_parent CONFIG=rv32i_zifencei
make lint COMPONENT=pipeline_ctrl CONFIG=rv32i
```

Use `PYTHON=.venv/bin/python` for the repository environment. Both
[standalone](../../../config/sim/pipeline_ctrl.yml) and
[parent](../../../config/sim/pipeline_ctrl_parent.yml) manifests use the common
runner. The enabled [preset](../../../config/rv32i_zifencei.yml) differs from
RV32I only by `ISA_ZIFENCEI=1`.

## Stage movement and metadata

`de_valid_i`, `ex_valid_i`, `mem_valid_i`, and `wb_valid_i` describe occupied
parent-owned slots. `*_complete_i` describe each local stage's valid result or
completed token, not occupancy. For actual stage wiring, use each stage's
`valid_o` as completion, its `ready_i` from the corresponding controller
`*_ready_o`, and DE's `permit_i` from `de_permit_o`. IF receives `if_permit_o`,
`if_ready_o` and `fetch_enable_o`; its `valid_o` supplies `if_valid_i`.

`*_fire_o` identify exactly one accepted transfer. A slot can drain without
replacement, leaving a bubble, and a stalled EX does not stop independent older
MEM/WB progress. Empty slots can fill while successors are stalled.
For each DE/EX/MEM/WB slot, the parent applies:

```verilog
always @(posedge clk_i) begin
    if (!rst_ni) begin
        ex_valid_q <= 1'b0;
    end else if (ex_enable) begin
        ex_valid_q <= ex_valid_next;
        if (ex_valid_next) begin
            // Capture the accepted DE payload, including PC/fault/serial state.
        end
    end
end
```

`*_valid_next_o` is the replacement valid value when its `*_enable_o` is high;
it is not an unconditional next-state expression during a hold. Flush forces
enable high and replacement invalid even if the stage cannot finish.
Payload registers need no reset or clearing. Hazard DE lifecycle clear is the
accepted DE transfer or DE flush, not every empty-slot enable.

`de_admit_i` can block DE issue/admission without blocking older work; this is
also the hook for later stepping/ID cleanup control. `commit_enable_i` controls
WB acceptance. WB commitment permission never depends on `wb_complete_i`,
accepted WB redirect signals, or coprocessor result fields. This preserves the
CV-X-IF result-ready rule when WB is later connected with XIF enabled.

Qualify all fault and serialization metadata with occupancy. EX/MEM/WB
`*_serialize_i` blocks younger DE admission through the serial token's actual
WB acceptance; it is not released by a younger redirect or an unrelated stall.
The DE serializer flag travels with that instruction into EX; it is not a
separate controller state bit. The next cycle observes committed CSR changes
before admitting younger work.

## Faults, effects and flush ownership

| Oldest known fault | Younger local units/parent slots flushed |
| --- | --- |
| WB | MEM, EX, DE |
| MEM | EX, DE |
| EX | DE |
| DE | None; retain/advance the fault token |

Any live fault stops new frontend work and flushes IF. Its owning instruction
can still advance toward WB while older instructions finish. A fault does not
flush its own local unit. Accepted WB recovery flushes all three younger
stages, never WB itself. WB's ordinary fire/parent enable consumes that slot;
feeding the accepted event back to WB's `flush_i` would cancel CSR updates or
form a loop. Normal controller wiring leaves WB local flush low (reset remains
its reset input).

Fault inputs must be live reports independent of the owning stage's downstream
ready. MEM/EX faults may depend on their own local completion, but must not be
gated by a successor handshake. Existing stage reports satisfy this distinction.

`mem_request_permit_o` covers reads and writes. It requires a live nonfaulting
MEM instruction, no known older WB fault/recovery, and either empty WB or
`wb_effect_safe_i`. That input is a proof that the older WB instruction cannot
subsequently fault, not merely that it is occupied, has a destination, or has
started execution. A valid proof may release the younger request before the
older instruction retires. A younger DE/EX fault never denies an older MEM
request. Once OBI request is presented, the LSU retains its protocol obligations
even if permission later drops; no flush is a rollback mechanism.

## Accepted events and interrupts

WB target calculation remains local to the event/CSR adapter. Supply the
instruction's accepted exception/MRET/DRET/debug event through
`wb_redirect_valid_i` / `wb_redirect_addr_i`; it must correspond to WB
acceptance. The controller additionally qualifies it with `wb_fire_o` and
selects it ahead of younger redirects. Do not echo an accepted synchronous
WB exception through WB's external `trap_i` input. FENCE.I success is selected
internally from the WB system tag and `wb_next_pc_i`.

The core supplies DE correction intent and the resolved next PC through
`de_redirect_i` / `de_redirect_addr_i`. Baseline modes use the accepted taken
branch report; bimodal mode compares the carried prediction with the actual
next PC, including taken-to-not-taken corrections. The controller qualifies
correction with DE transfer, suppresses IF capture/new fetching that cycle,
and redirects without flushing that same DE instruction. Older faults and
accepted WB events prevent the DE transfer/redirect. Correct predictions do
not request a redirect.

Machine eligibility uses live `mie_i`, `mip_i`, `mstatus_i`, `priv_m_i` and
`irq_mask_i`. Only causes 11, 3 and 7 participate, in external/software/timer
priority order. In M-mode MIE is required; in U-mode machine delivery does not
depend on MIE. This follows the
[machine interrupt rules](https://docs.riscv.org/reference/isa/priv/machine.html).
The core supplies `irq_mask_i` for Debug Mode or single stepping. No pending
interrupt is latched here and entry does not clear a source.

While eligible, block new DE-to-EX admission and XIF issue through DE permit,
but allow EX/MEM/WB to finish. Entry requires those occupied slots already be
empty and `drain_ready_i` true. This waits one cycle after the last WB transfer,
observing resulting CSR/privilege changes. Withdrawn eligibility immediately
releases a preserved DE instruction, including its fault. A DE fault loses to
eligible interrupt entry; an older fault finishes its normal WB trap path first.

`trap_valid_o`, `trap_pc_o`, `trap_interrupt_o`, `trap_cause_o`, and zero
`trap_tval_o` are the accepted external WB/CSR interrupt event. The saved PC is
`de_pc_i` when DE is occupied, otherwise `resume_pc_i`: the core-owned next
architecturally unexecuted PC, not the speculative fetch pointer. `mtvec_i`
selects full-width Direct/Vectored arithmetic with 32-bit address wraparound.

The higher-priority normalized `drain_req_i` / `drain_target_i` endpoint uses
the same EX-entry drain boundary. It reports `drain_accept_o` and `drain_pc_o`
without generating a machine trap. A qualified external debug halt can use it
after its requester handles request capture and debug cause/state. WB recovery
occurs first if an older instruction faults; keeping the request active then
accepts at the post-trap handler PC. This endpoint is core-internal, not a new
coprocessor signal or a complete external-DM interface.
The requester must remove or requalify its request after acceptance; a held raw
DM request must not repeatedly enter through this endpoint.

The core must keep `drain_ready_i` low until accepted data transactions and
required DE-only XIF kill cleanup finish. The [core](../core/README.md) connects
XIF ID ownership, standard commit-kill arbitration and replay after canceled
eviction through its XIF controller. Debug request/step sequencing and Debug Mode
remain future core adapters. Cleanup must keep `de_admit_i` low while unfinished
and arrange restart of an evicted instruction if entry is canceled. Native
configurations can tie cleanup readiness high once relevant data work has finished.

## Fences

The parent carries `UQU_SYS_FENCE`/`UQU_SYS_FENCEI` tags to WB. `data_idle_i`
confirms completion of relevant older native/custom memory work. A live,
nonfaulting WB fence then asserts its matching request independently of ack or
commitment stalls. Once presented, the request stays asserted until its matching
ack, even if `data_idle_i` subsequently falls. Acknowledgement on the other
interface cannot complete it.

If ack arrives while commitment is disabled, one controller bit remembers it
and suppresses duplicate requests. A second bit remembers request presentation.
The fence can then retire once when WB commitment is enabled, without another
external acknowledgement. Reset, emptied WB, WB fault and WB acceptance clear
this state. A faulting fence bypasses synchronization to take its exception.
FENCE.I also stops new fetches while its tag is anywhere in the pipeline and
redirects to `wb_next_pc_i` on successful acceptance. Base FENCE does not
invalidate IF. Disabled FENCE.I must already have been rejected by DE.

## Verification

- `movement`: every occupancy/completion/commit/admission combination, empty
  replacement, old-stage progress, serial barriers and same-cycle DE redirects.
- `faults`: age-qualified fault combinations, stalled containment, primary WB
  recovery and data-read/write permission before/after proof of older safety.
- `interrupts`: source masks, M/U/global enable and source priority, DE-fault
  preemption, older-stage drain, withdrawn eligibility, handler wraparound and
  the higher-priority generic drain endpoint.
- `fences`: request retention, independent acks, remembered ack while stalled,
  exactly-once acceptance/restart, faults and reset cancellation.
- `randomized`: 8,192 control vectors per seed against an age/transaction oracle
  whose fence protocol uses idle/waiting/acknowledged states.

The [parent fixture](../pipeline_ctrl_parent/README.md) adds actual boundary
storage, MEM/LSU and WB/CSR effects. Lint and Yosys checks include zero
combinational strongly connected components, two controller state bits, no
latches/asynchronous resets, and no WB-completion/event-to-WB-ready or
WB-completion/event-to-interrupt-entry combinational path. These are component
and fixture checks, not a complete processor or software/Spike comparison.
