# Write-back stage

[uqu_stage_wb.v](../../../src/uquintus/uqu_stage_wb.v) owns one
[uqu_csregfile](../csregfile/README.md), result selection and commitment logic.
The core parent owns MEM/WB, the GPR file, current privilege and Debug Mode,
serialization, global event arbitration, redirects and core-wide PMP. WB owns
no pipeline payload/valid registers. With XIF enabled it retains one bit to
remember commit permission for the current parent-held token.

## Input slot and commitment

| Ports | Meaning |
| --- | --- |
| `clk_i`, `rst_ni`, `flush_i` | Single clock, active-low synchronous reset, cancellation of the owning uncommitted token. |
| `valid_i`, `ready_o` | Parent-held MEM/WB token and permission to fill/replace it. An empty slot may fill while retirement is blocked. |
| `valid_o`, `ready_i` | Completed WB candidate and controller authorization to finalize it. Acceptance is `valid_o && ready_i`. |
| `kind_i[2:0]` | 0=ordinary result/nonwriter, 1=CSR, 2=MRET, 3=XIF, 4=DRET, 5=EBREAK; 6/7 illegal. Decode validates encodings and serializes control instructions. |
| `result_i[31:0]`, `rd_we_i`, `rd_i[4:0]` | Ordinary result/destination intent; CSR destination intent is implicit. For XIF, rd identifies the issue instruction's destination; standard result.we supplies write intent. |
| `pc_i[31:0]`, `instr_i[31:0]` | Original instruction identity for precise faults and EBREAK entry. |
| `csr_addr_i[11:0]`, `csr_op_i[2:0]`, `csr_src_i[31:0]`, `csr_src_zero_i` | Decoded CSR address/funct3, resolved operand, and register-source-is-x0 encoding. Immediate operands use bits 4:0. |
| `fflags_valid_i`, `fflags_i[4:0]` | Per-instruction FP status for normal Zfinx results. |
| `exception_valid_i`, `exception_cause_i[4:0]`, `exception_tval_i[31:0]` | Existing synchronous exception, with priority over local legality checks. |
| `priv_m_i` | Parent-owned current privilege, valid even with no WB token. Debug entry saves this privilege; debug execution uses machine CSR permissions. |
| `hart_id_i[31:0]`, `irq_software_i`, `irq_timer_i`, `irq_external_i` | Integration identity and synchronous interrupt levels. |

Retain the token until acceptance or permitted cancellation and consume it once
on acceptance. Normal results may retire on consecutive cycles. A held native
instruction does not repeat CSR/GPR/FP effects. CSR queries have no side effects
until commit. Fence/serialization readiness comes from the controller. All
ordinary destination writes, CSR updates and committed flags belong to the same
retirement edge. x0 never writes; actual E destinations x16..x31 fault without
aliasing; unused rd fields do not fault.

## Memory completion

`lsu_i` marks an accepted data transaction whose identity resides in MEM/WB.
WB waits for `lsu_res_valid_i`; `lsu_res_ready_o` depends on ownership and
retirement authorization, independently of response data/validity. A successful
load selects `lsu_res_data_i` for its GPR write; a store retires without writing.
The `lsu_res_exception_*` inputs instead cause precise trap entry using the
retained WB PC and original effective address, with no ordinary retirement.

A raw response may write the architectural register file at its retirement
edge. `result_valid_o` remains low until `lsu_res_registered_i` indicates a
buffered response. Consumers therefore use registered forwarding or read the
GPR after load retirement; no external response feeds dependent DE/EX logic.
The LSU captures a response if WB cannot consume it. Parent cancellation must
also cancel LSU response ownership; the core never cancels its oldest WB memory
transaction and routes younger MEM flushes separately.

## Results and exceptions

| Ports | Meaning |
| --- | --- |
| `retire_o` | Successful accepted instruction; feeds minstret once, subject to inhibit/debug counter rules. EBREAK entry/end and faults do not retire. |
| `exception_valid_o`, `exception_cause_o[4:0]`, `exception_tval_o[31:0]`, `exception_pc_o[31:0]` | Live synchronous fault report, independent of readiness and accepted external events. |
| `exception_fire_o` | Accepted normal-mode fault; captures machine trap CSRs, without ordinary writes/retirement. |
| `mret_o` | Accepted legal MRET; parent samples pre-edge MPP/mepc to restore privilege/PC. |
| `we0_o`, `waddr0_o[4:0]`, `wdata0_o[31:0]` | Retirement-qualified primary GPR write. |
| `we1_o`, `waddr1_o[4:0]`, `wdata1_o[31:0]` | Simultaneous secondary paired-XIF write; otherwise zero. |
| `result_valid_o`, `result_o[31:0]` | Primary destination available for parent forwarding. Ordinary/matching XIF data may be advertised while held; CSR data only on successful retirement. |

GPR write address/data outputs are zero when their write enable is zero.
`result_o` is an unmasked forwarding candidate; `result_valid_o` qualifies its
use. Loads use the separate `lsu_res_forward_data_i` from the existing LSU
response register, while retirement may use live `lsu_res_data_i`. No response
register or forwarding cycle is added, and live load data is never bypassed.
CSR results are
architectural pre-update read values. Held counter queries may change, so CSR
results are not forwardable before commitment. Existing exceptions win over
malformed controls and CSR checks. Disabled XIF, DRET outside Debug Mode,
U-mode MRET, reserved classes, invalid FP-status controls and E destination
violations report illegal instruction with original instruction bits. MRET in
Debug Mode also uses this exception path (its architectural behavior is
unspecified). EBREAK with debug entry disabled is a breakpoint exception with
its PC in tval. Decode emits the EBREAK class without a preexisting exception
when applying the debug-break controls.

The parent forwarding/hazard block still performs matching and youngest-writer
selection and applies configured bypass paths. It must retain secondary paired
destination hazards until register-file visibility; no secondary forwarding
output is provided.

## CV-X-IF commit and results

`XIF=1` implements the WB endpoint of the
[CV-X-IF v1.0.0 profile](../../../doc/uqu_spec.interfaces.md#5-cv-x-if-custom-extension-interface).
Only standard commit/result signals and packet fields reach the coprocessor.
The timing rules are defined in the standard's
[commit interface](https://docs.openhwgroup.org/projects/openhw-group-core-v-xif/en/v1.0.0/x_ext.html#commit-interface)
and [signal dependencies](https://docs.openhwgroup.org/projects/openhw-group-core-v-xif/en/v1.0.0/x_ext.html#signal-dependencies):

| Ports | Standard mapping |
| --- | --- |
| `xif_commit_valid_o` | commit_valid (implicit always ready). |
| `xif_commit_hartid_o[31:0]`, `xif_commit_id_o[2:0]`, `xif_commit_kill_o` | commit.hartid/id/commit_kill. |
| `xif_result_valid_i`, `xif_result_ready_o` | result_valid/result_ready. |
| `xif_result_hartid_i[31:0]`, `xif_result_id_i[2:0]` | result.hartid/id. |
| `xif_result_data_i[32*(1+XIF_DUALWRITE)-1:0]`, `xif_result_rd_i[4:0]`, `xif_result_we_i[XIF_DUALWRITE:0]` | result.data/rd/we. |

The core-side `xif_id_i[2:0]` travels in the parent MEM/WB token. Issue/operand
channels, up to four live pipeline offloads, ID allocation/reuse and dependency
tracking remain in the core parent/DE integration; WB adds no issue/result queue.
The hart-ID field is 32 bits. The native core ties this component's `hart_id_i`
to its compile-time `HART_ID` parameter; it is not an exposed core input.

For a surviving XIF token WB sends exactly one commit notification with kill=0,
independently of result validity or ready_i. This avoids deadlock with a
coprocessor that waits for permission before returning a result. WB then holds
its parent slot until the matching hart/ID packet is available and ready_i
permits retirement. Permission and result acceptance may share an edge. The
coprocessor may compute before permission and expose its prepared result
combinationally from commit_valid/commit_kill. GPR writes still occur on the
active clock edge; combinational completion adds no mandatory clock cycle. Result
acceptance, GPR writes and retirement always share an edge; no early result
acceptance/buffer is needed. Result data remains in the coprocessor under
backpressure. result_ready is generated from WB capacity/authorization and
commit permission, independently of result_valid and all result packet fields,
following CV-X-IF's signal-dependency rule. The parent must also supply ready_i
independently of incoming XIF result signals. Zero-write results still complete
and retire once. The coprocessor
must present surviving results in accepted issue order and keep a stalled
packet stable.

With XIF_DUALWRITE=1, we=3 writes the lower/upper 32-bit words to even rd and
rd+1 simultaneously. we=1 writes a single register (including odd rd); we=0
writes none. A pair at rd=0 is ignored in its entirety. Only primary data is
forwarded. Mismatched hart/ID, mismatched writing rd, E-register violations,
odd paired rd, and we=2 do not retire or write GPRs. Since result_ready cannot
depend on packet fields, an invalid packet may handshake and be discarded while
WB continues waiting. These are integration/protocol violations requiring
integration-level diagnosis/recovery, not coprocessor-generated CPU exceptions; no execution trap sideband
is introduced. Issue must validate register legality and record write hazards
before permission. As permitted by CV-X-IF, WB does not recheck issue-response
writeback flags against result.we.

Core-internal `xif_kill_valid_i`, `xif_kill_id_i[2:0]`,
`xif_kill_ready_o` arbitrate younger speculative kills onto the same standard
commit output. Hold the internal kill request until ready; a WB notification
has priority. This is a parent-to-WB connection, **not** a coprocessor sideband.
An owning flush of an unpermitted WB XIF token sends its kill on that edge;
the parent then clears the slot. An acknowledged existing core fault likewise
sends kill instead of permission. Once allowed to commit, an XIF token must
finish: the parent must neither flush/replace it nor assert interrupt/debug
entry before its result completes. Younger DE kills remain independently
serviceable while WB waits. Standard commit permission also covers older IDs;
a standard kill covers the named ID and all newer offloads of that hart. The
parent must discard all affected pipeline/tracking entries, avoid killing an
already-permitted WB instruction, and block new surviving issue on the kill
edge (its issue transaction may start no earlier than the following cycle).
Rejected issue transactions also require a standard final commit/kill notice,
supplied through parent tracking rather than a WB result token. Reset requires
coordinated coprocessor reset.

With XIF=0 all core-driven XIF outputs are zero and result/kill inputs are
ignored. An XIF-class token faults. Disabled paired-write logic has no storage
or active secondary write path.

## Minimal debug endpoint

`DEBUG=1` enables WB/CSR support for
[Debug 1.0 Sdext](https://docs.riscv.org/reference/debug/v1.0/Sdext.html).
The core controller owns Debug Mode, external-halt/reset-halt/step arbitration,
DE blocking and pipeline/bus/XIF draining. WB does not accept a raw halt request.

| Ports | Meaning |
| --- | --- |
| `debug_mode_i` | Current parent-owned Debug Mode. |
| `debug_enter_i`, `debug_pc_i[31:0]`, `debug_cause_i[2:0]` | Previously arbitrated entry pulse and precise resume PC/cause (halt=3, step=4, reset-halt=5). Entry saves DPC, DCSR.prv/cause and suppresses WB acceptance. |
| `debug_enter_o` | Accepted external entry or accepted EBREAK entering debug. Parent enters Debug Mode/M privilege and redirects to debug_entry_addr_i. |
| `dret_o` | Accepted serialized DRET; parent exits Debug Mode and restores pre-edge DPC/DCSR.prv. CSR state clears MPRV for a U return. |
| `debug_exception_o` | Accepted fault in Debug Mode; parent redirects to debug_exception_addr_i. Machine trap CSRs remain unchanged. |
| `debug_ebreak_o` | Accepted EBREAK already in Debug Mode; ends program-buffer/debug execution through the DM's debug-ROM completion path, without replacing DPC/DCSR. |
| `dcsr_o[31:0]`, `dpc_o[31:0]` | CSR-owned debug state for controller use. |

DCSR/DPC/dscratch0 at 7B0/7B1/7B2 are accessible only in Debug Mode. The single
scratch register is for a compatible minimal external-DM ROM; dscratch1 and
hardware triggers are not implemented. DCSR implements ebreakm, step, cause,
and optional ebreaku/prv state. Debugver=4, stopcount=1, mprven=1; stepie=0,
stoptime=0, unsupported fields zero. Unsupported prv writes select M. With
mprven=1 the parent retains normal MPRV memory-privilege handling; no relaxed
PMP bypass is implied. DPC aligns like mepc. All debug fields reset synchronously.

A normal-mode EBREAK with its current privilege's ebreak control set enters
debug with cause=1 and DPC at that instruction. No trap CSR, ordinary destination
or retirement update occurs; hart-local counters also do not increment on its
entry edge. EBREAK with the control clear takes a normal breakpoint exception.
Counters freeze while in Debug Mode, including debug ROM/program-buffer
instructions, but explicit legal counter writes remain available.

After DRET with DCSR.step=1, the controller masks interrupts, permits exactly
one architectural instruction, and uses retirement/fault completion to select
reentry with the actual next PC. A stepped fault first completes normal trap
entry, then a later debug-entry event saves the handler PC before handler
execution. External halt after an older draining fault follows the same
post-trap sequencing with halt cause. These are controller responsibilities;
WB exposes events/state without inventing an extra DM interface. The parent
must apply Debug 1.0 cause priority before supplying an accepted event.

Accepted external debug entry takes defensive priority over a simultaneous
external trap; valid integration arbitrates first. Interrupt trap events are
ignored in Debug Mode. With DEBUG=0 debug outputs/state are zero, debug inputs
are ignored and debug CSR/DRET accesses fault.

## Architectural events and integration

`trap_i`, `trap_pc_i[31:0]`, `trap_interrupt_i`, `trap_cause_i[4:0]`, and
`trap_tval_i[31:0]` carry a previously arbitrated precise external trap, normally
an interrupt after draining. Raw IRQ levels alone never enter a trap. The
controller prioritizes older WB faults before asserting external trap/debug
entry. Accepted external events can update owned CSR state during owning flush;
reset dominates. A fault acknowledged by exception_fire_o already updates trap
CSRs: do not echo it through trap_i.

Do not feed accepted fault/MRET/DRET/local-debug events combinationally back
into WB flush_i; that would cancel the acceptance generating the event. Consume
the token, clear younger slots and block wrong-path refill separately. The
[parent fixture](../wb_pipeline/README.md) demonstrates this boundary.

`mstatus_o`, `mie_o`, `mip_o`, `mtvec_o`, `mepc_o` expose architectural state.
`pmpcfg_o[127:0]` and `pmpaddr_o[511:0]` route through the parent to its PMP
instance; `frm_o[2:0]`/`fflags_o[4:0]` expose optional FP state. Target arithmetic,
current privilege and global sequencing remain outside WB.

## Configuration and verification

Parameters: ISA_E/M/C/ZFINX/F/A/UMODE/PMP, XIF, XIF_DUALWRITE and DEBUG. Full F
and A remain unsupported; Zfinx CSR wiring does not implement an FPU.
CSR storage is `265 + ISA_C + 5*ISA_UMODE + 8*ISA_ZFINX + 608*ISA_PMP
+ DEBUG*(67 + ISA_C + 2*ISA_UMODE)` bits, plus exactly one local permission bit
when XIF=1. No boundary payload storage is added.

```sh
make test COMPONENT=wb CONFIG=rv32i
make test COMPONENT=wb CONFIG=rv32i_xif_debug
make test COMPONENT=wb_pipeline CONFIG=rv32i_xif_debug
make lint COMPONENT=wb_pipeline CONFIG=rv32i_xif_debug
```

The cocotb/pyuvm suites share architectural [CSR](../common/csregfile_model.py)
and [WB](../common/wb_model.py) models. Native directed/control/randomized suites
check commitment, CSR forms, faults, counters, flags, stalls/reset/flush and
MRET. `xif` checks delayed and same-cycle results (including combinational response to permission), permission once, foreign
IDs/harts, pending younger kills, ID wrap, paired/x0/E behavior, nonwriters and
pre-permission cancellation. `debug` checks access restrictions, WARL state,
counter freezing/explicit writes, DRET, EBREAK controls, step entry and debug
exceptions. The parent fixture verifies physical GPR writes and mode changes.
The [core](../core/README.md) connects native/XIF draining, DE issue/ID tracking
and paired writeback. RVFI/CSR, ELF and scoped Spike tests add integrated native
verification; XIF has its own behavioral oracle and companion trace. Core debug
and external-DM operation remain open.
