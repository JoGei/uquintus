# Write-back stage

[uqu_stage_wb.v](../../../src/uquintus/uqu_stage_wb.v) owns one
[uqu_csregfile](../csregfile/README.md), result selection and commitment logic.
It adds no local state or pipeline payload registers. Its core parent owns
MEM/WB, the GPR file, current privilege, serialization, trap/interrupt/debug
arbitration, redirects, and the core-wide PMP block. Tracing/RVFI remain
verification-side observers.

## Input slot and commitment

| Ports | Meaning |
| --- | --- |
| `clk_i`, `rst_ni`, `flush_i` | Single clock, active-low synchronous reset, and cancellation of the owning WB instruction. |
| `valid_i`, `ready_o` | Parent-held MEM/WB token and permission to fill/replace the slot. Empty slots may fill while commitment is blocked. |
| `valid_o`, `ready_i` | Live WB candidate and controller authorization to finalize it. Acceptance is `valid_o && ready_i` at the active edge. |
| `kind_i[1:0]` | 0=ordinary MEM result/token, 1=CSR, 2=MRET, 3=unsupported XIF control (illegal instruction). |
| `result_i[31:0]`, `rd_we_i`, `rd_i[4:0]` | Ordinary result and decoded GPR destination intent. CSR destination intent is implicit in its instruction class; MRET has none. x0 never writes. |
| `pc_i[31:0]`, `instr_i[31:0]` | Original instruction identity for precise fault capture and illegal-instruction trap value. |
| `csr_addr_i[11:0]`, `csr_op_i[2:0]`, `csr_src_i[31:0]`, `csr_src_zero_i` | Decoded CSR address/funct3, resolved register/immediate operand, and register-source-is-x0 encoding. Immediate operands use bits 4:0. Destination-is-x0 is derived from `rd_i`. |
| `fflags_valid_i`, `fflags_i[4:0]` | Per-instruction FP status from a normal Zfinx result. |
| `exception_valid_i`, `exception_cause_i[4:0]`, `exception_tval_i[31:0]` | Existing synchronous exception, with priority over local checks and no CSR query. |
| `priv_m_i` | Current core execution privilege, valid even when MEM/WB is empty. The parent owns mode transitions; this is not an uninitialized payload bit. |
| `hart_id_i[31:0]`, `irq_software_i`, `irq_timer_i`, `irq_external_i` | Existing integration identity and synchronous interrupt levels, passed to CSR state. |

The parent retains the input token until acceptance or owning cancellation and
must consume it on each acceptance. No stage-issued bit is needed: there is no
early native-unit issue, and all token side effects occur together on acceptance.
Holding `ready_i=0` suppresses ordinary CSR/GPR/flag updates and retirement,
while mcycle follows its usual inhibit rules. Once accepted, an identical next
instruction may commit on the next cycle. One ordinary token per cycle is supported.

`ready_i` must authorize normal retirement or synchronous fault entry according
to the reported exception. It also incorporates external requirements for
fences and serialized operations; WB does not decode instructions or implement
fence request/acknowledgement sequencing. Decode still validates instruction
encodings, register sources, WFI permissions, and operation classification.

## Architectural outputs and faults

| Ports | Meaning |
| --- | --- |
| `retire_o` | Accepted, nonfaulting instruction. Feeds the owned CSR counter input once, including CSR instructions and legal MRET. |
| `exception_valid_o`, `exception_cause_o[4:0]`, `exception_tval_o[31:0]`, `exception_pc_o[31:0]` | Live synchronous fault report, independent of readiness and accepted external trap input. Zero metadata without a report. |
| `exception_fire_o` | Controller accepted this WB fault. Captures synchronous trap state in CSR once; no normal retirement/GPR/FP update. |
| `mret_o` | Accepted legal MRET; CSR state restoration and normal retirement occur at this edge. Parent restores mode and redirects using pre-edge MPP/mepc. |
| `we0_o`, `waddr0_o[4:0]`, `wdata0_o[31:0]` | Primary GPR write pulse and data, qualified by successful retirement and nonzero implemented destination. Address/data zero when not writing. |
| `we1_o`, `waddr1_o[4:0]`, `wdata1_o[31:0]` | Constant zero until the deferred XIF paired-write implementation. |
| `result_valid_o`, `result_o[31:0]` | Available primary destination value for parent forwarding logic. Ordinary results may be available while held; CSR results only on successful retirement. No value for x0, stores/nonwriters, MRET, or faults. |

An enabled E configuration rejects actual GPR destinations x16..x31; unused
rd fields do not fault. Unsupported XIF class, illegal user MRET, and invalid
FP-status/class/configuration combinations report illegal instruction with
original bits as tval. CSR failures use the CSR module's report. Existing
exceptions take priority over all of these checks.

CSR reads observe the pre-update state at their actual commitment edge. A held
counter query can change as mcycle advances, so it is not advertised as a
forwardable value until commitment. All normal GPR writes, CSR writes, committed
FP flags, and retirement are qualified by the same acceptance. The separate
hazard/forwarding block must still apply destination matching, youngest-writer
selection and configured-path policy. CSR serialization prevents younger
consumers from proceeding before the CSR instruction completes.

## Accepted traps and parent responsibilities

`trap_i`, `trap_pc_i[31:0]`, `trap_interrupt_i`, `trap_cause_i[4:0]`, and
`trap_tval_i[31:0]` carry a **previously arbitrated external architectural trap
event**, normally an interrupt at a drained boundary. It is not a raw IRQ request.
Reset dominates. An accepted external trap suppresses WB candidate acceptance
and directly updates CSR trap state, even during cancellation of the WB token.
It does not retire an instruction. IRQ levels alone never initiate a trap here.

The controller must prioritize an older live WB fault over an interrupt *before*
asserting `trap_i`, and ensure the event's PC/current privilege describe the
precise boundary. The fault report deliberately does not depend on `trap_i` or
`ready_i`, avoiding an arbitration loop. Defensive collisions give the accepted
external event priority, but are not permission to violate core event ordering.

A WB fault acknowledged through `exception_fire_o` already updates trap CSR
state. **Do not echo it back through `trap_i`.** The controller redirects using
that accepted fault and the pre-edge mtvec state. Likewise, do not feed a WB
instruction's own fault/MRET acceptance combinationally back to its `flush_i`;
that would cancel the very acceptance generating the flush. Consume that token
normally, clear/block younger parent slots separately, and prevent wrong-path
refill. The [parent fixture](../wb_pipeline/README.md) demonstrates this boundary.

State outputs `mstatus_o`, `mie_o`, `mip_o`, `mtvec_o`, `mepc_o` are architectural
32-bit views. `pmpcfg_o[127:0]`, `pmpaddr_o[511:0]` route through the core parent
to its one two-port PMP instance. `frm_o[2:0]` and `fflags_o[4:0]` expose optional
FP CSR state. Current privilege, target arithmetic and global event sequencing
remain outside WB. Ordinary owning flush does not roll back committed state or
stop cycle counting. Reset follows the CSR contract, including unreset enabled
PMP address payloads.

## Configuration and verification

Parameters are `ISA_E`, `ISA_M`, `ISA_C`, `ISA_ZFINX`, `ISA_F`, `ISA_A`,
`ISA_UMODE`, `ISA_PMP`, `XIF`, and `DEBUG`. The selected baseline supports native
write-back with `XIF=0`, `DEBUG=0`, `ISA_F=0`, `ISA_A=0`. Enabled unsupported
settings fail elaboration. Zfinx CSR/commit wiring does not implement an FPU.
The stage adds no storage beyond its CSR unit's existing configuration-dependent
state budget: `265 + ISA_C + 5*ISA_UMODE + 8*ISA_ZFINX + 608*ISA_PMP` bits.

```sh
make test COMPONENT=wb CONFIG=rv32i
make lint COMPONENT=wb CONFIG=rv32i
make test COMPONENT=wb_pipeline CONFIG=rv32i
```

The project cocotb/pyuvm suites share the existing CSR-word model and a
[WB architectural model](../common/wb_model.py). `directed` checks GPR
qualification, all CSR forms and suppression, faults, class guards, x0/E,
flags, and counters. `control` checks held results/CSR/faults, commitment versus
reporting, flush/reset, accepted external events, MRET and consecutive identical
tokens. `randomized` checks 2,048 mixed tokens with independent stalls and events.

Development regressions cover all sixteen U/C/Zfinx-CSR/PMP combinations with
representative I/E/M settings. The real-parent/GPR fixture additionally runs
with FF and latch register files. Representative Yosys checks confirm one CSR
unit, no extra WB state/boundary storage, no GPR/PMP instance, constant secondary
write outputs, and no latches/memories/combinational loops. This is a component
milestone: full-core controller/serialization, XIF paired write-back, debug,
RVFI, and architectural software/reference-model verification remain pending.
