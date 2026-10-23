# Architectural CSR register file

`src/uquintus/uqu_csregfile.v` implements the [CSR contract](../../../doc/uqu_spec.arch.md#18-native-csr-instruction-execution)
as decoded state fields, not a 4,096-word writable array. It is plain
Verilog-2005 and completes CSR evaluation combinationally with one-edge updates.
The parent owns WB serialization, current privilege, retirement qualification,
trap selection, redirects, and age-qualified cancellation. No complete WB or
core controller is implemented by this component.
The [WB stage](../wb/README.md) now instantiates this unit and qualifies its
commit/retirement events; the full-core parent still owns global arbitration.

Parameters are `ISA_E`, `ISA_M`, `ISA_C`, `ISA_ZFINX`, `ISA_F`, `ISA_A`,
`ISA_UMODE`, `ISA_PMP`, and `DEBUG`. I/E, M, C, and U determine hardwired `misa`.
Zfinx adds only FP CSR state and does not set `misa.F` or require `mstatus.FS`.
Full F and atomics remain deferred: `ISA_F=1` and `ISA_A=1` fail elaboration.
`DEBUG=1` enables compact debug CSR state and counter control. Boolean parameters reject values
outside zero/one. Enabling Zfinx CSR storage does not implement the FPU.

## Access interface

| Ports | Contract |
| --- | --- |
| `clk_i`, `rst_ni` | Single clock, active-low synchronous architectural reset. All state resets except enabled PMP address payloads. |
| `csr_valid_i` | A live CSR instruction being evaluated in WB. It may remain asserted while WB is held. |
| `csr_commit_i` | Parent-generated one-cycle commitment pulse for this instruction; never repeatedly assert for a held instruction. |
| `flush_i` | Discard this CSR access; suppress its response validity and explicit writes. Does not cancel independent older architectural events or cycle counting. |
| `csr_addr_i[11:0]` | CSR address. |
| `csr_op_i[2:0]` | Instruction funct3: 1/2/3 = CSRRW/CSRRS/CSRRC; 5/6/7 = immediate forms; 0/4 illegal. |
| `csr_src_i[31:0]` | Register operand, or immediate value in bits 4:0 (upper bits ignored for immediate forms). |
| `csr_src_zero_i` | Register source encoding is x0, independent of its value. Ignored for immediate forms, which inspect the five-bit immediate. |
| `csr_rd_zero_i` | Destination encoding is x0; suppresses CSRRW[I] read intent only. |
| `csr_instr_i[31:0]` | Original instruction, used as illegal-instruction trap value. |
| `priv_m_i`, `hart_id_i[31:0]` | CSR access/MRET privilege (M=1/U=0) and stable integration hart identity. Parent supplies the owning instruction's context; M-only builds execute in M-mode. |
| `event_priv_m_i` | Privilege saved on accepted trap/debug entry. Independent of access permission; valid for the event even without a CSR instruction. |
| `csr_read_o`, `csr_write_o` | Legal, live read/write **intents**, independent of `csr_commit_i`. They are not update pulses. |
| `csr_rdata_o[31:0]` | Pre-edge architectural read value; zero if no legal live read is requested. |
| `csr_exception_valid_o`, `csr_exception_cause_o[4:0]`, `csr_exception_tval_o[31:0]` | Live invalid access reports illegal-instruction cause 2 and original instruction; data/intent outputs are suppressed. Cause/value are zero without an exception. |

No request/result buffer, ready handshake, or extra CSR access cycle is needed.
Explicit state changes require valid, commit, legal write intent, reset released,
no owning flush, and no simultaneous trap/MRET event. An error cannot explicitly
write state even if the parent incorrectly asserts commit. The parent uses the
error report to suppress GPR writes and normal retirement and to enter the trap
through its existing WB exception path.

CSRRS/CSRRC with a non-x0 source containing zero still request a write; their
x0-source forms do not. Immediate zero forms suppress set/clear writes. CSRRW[I]
always requests a write, including zero. Hardwired fields in writable CSR
addresses ignore or legalize writes rather than making the CSR read-only.

## Architectural events and state outputs

| Ports | Contract |
| --- | --- |
| `irq_software_i`, `irq_timer_i`, `irq_external_i` | Synchronous levels read directly as `mip[3]`, `[7]`, `[11]`; no pending storage or clear-on-read. |
| `retire_i` | One already-qualified successful instruction retirement. Parent must exclude faults, killed instructions, and stalled repetitions. CSR accesses and MRET count through this input, not by inference in this module. |
| `trap_i` | One accepted trap-entry event. Captures `trap_pc_i[31:0]`, `trap_interrupt_i`, `trap_cause_i[4:0]`, `trap_tval_i[31:0]`; copies MIE to MPIE, clears MIE, and saves `event_priv_m_i` into MPP. Parent changes current privilege to M. |
| `mret_i` | One accepted legal M-mode return event. Restores MIE from MPIE, sets MPIE, resets MPP to the least privilege implemented, and clears MPRV when returning to U. Parent uses the pre-edge MPP/mepc for privilege/PC restoration. A U-mode event is ignored here; instruction legality is the decoder/controller's responsibility. |
| `fp_flags_valid_i`, `fp_flags_i[4:0]` | Already committed, age-qualified Zfinx accrued flags; ignored when Zfinx is disabled. OR into fflags. An explicit fflags/fcsr write overrides same-edge accrual; a frm-only write leaves accrual active. |
| `mstatus_o`, `mie_o`, `mip_o`, `mtvec_o`, `mepc_o` | Architectural 32-bit values for controller/datapath use, assembled from actual state and constants. Effective data privilege from MPRV/MPP is selected by the parent. Vectored target arithmetic remains outside this storage unit. |
| `pmpcfg_o[127:0]`, `pmpaddr_o[511:0]` | CSR-owned state for the core-owned two-port PMP block. Entry zero occupies the low bits; disabled PMP drives constant zero. |
| `frm_o[2:0]`, `fflags_o[4:0]` | Shared FP control/status views, constant zero when disabled. |

Reset has highest priority. Accepted trap entry wins over MRET, which wins over
ordinary explicit CSR writes. A trap/MRET event suppresses all ordinary CSR
writes, including writes to unrelated registers. Implicit counter progression
and separately qualified FP events are independent of this priority; the parent
must arbitrate event validity and faulting-instruction retirement correctly.
It must not treat `csr_commit_i` as a substitute for `retire_i`.

Both 64-bit counters count independently, using the **old** mcountinhibit value
on a control-write edge. A write to either half of a counter overrides that
counter's entire implicit increment for the edge, preserving the unwritten
half. Thus a write to minstret does not add one for that instruction. Read-only
aliases share counter storage. Stalls/CSR flush do not stop mcycle.

## Implemented map and storage

| CSRs | Behavior / actual storage |
| --- | --- |
| `fflags`/`frm`/`fcsr` 001/002/003 | Zfinx only: five flags plus three rounding bits, shared aliases; zero reset. No FS state. |
| `mstatus` 300 | MIE/MPIE; with U enabled also one MPP-is-M bit, MPRV, TW. Reset MPP=M, others zero. MPP writes 1/2 map to M; M-only MPP is constant M and MPRV/TW zero. All other fields read zero. |
| `misa` 301 | Constant configured RV32 I/E/M/C/U identification; permitted writes ignored. No invented multi-letter or XIF bit. |
| `mie`/`mip` 304/344 | Three enable state bits; pending levels are inputs. All other bits zero. Enables reset zero. |
| `mtvec` 305 | Thirty BASE bits plus one MODE bit; Direct/Vectored supported, modes 2/3 map to Direct with BASE retained. Reset zero. |
| `mcounteren` 306 | U-mode builds only, CY/IR state bits, reset zero; HPM/TM permissions zero. |
| `mstatush` 310 | Mapped zero, permitted writes ignored. |
| `menvcfg`/`menvcfgh` 30A/31A | Mapped zero only with U enabled, otherwise unmapped. |
| `mcountinhibit` 320 | CY/IR state bits, reset zero. |
| `mscratch`/`mtval` 340/343 | Full 32-bit state each, reset zero. |
| `mepc` 341 | Bits 31:2 with C disabled, 31:1 with C enabled; other bits zero. Reset zero; same alignment for explicit writes and trap capture. |
| `mcause` 342 | Interrupt flag plus four low cause bits; other bits zero. Covers all baseline causes, reset zero. Unsupported WLRL software-write codes deterministically retain low four bits; adding causes >=16 requires revisiting this width. |
| `pmpcfg0..3` / `pmpaddr0..15` 3A0..3A3 / 3B0..3BF | With PMP: six configuration bits plus 32 address bits per entry. Config bits 6:5 zero; reserved W=1/R=0 maps to W=0. Config resets zero; addresses unreset. L locks its own cfg/address even in OFF mode; a locked TOR also locks its predecessor address. Reset clears locks and preserves address payloads. With PMP disabled: mapped zero, permitted writes ignored. Later PMP entries are unmapped. |
| `mcycle[h]`/`minstret[h]` B00/B80/B02/B82 | Two 64-bit counters, zero reset. |
| `cycle[h]`/`instret[h]` C00/C80/C02/C82 | Read-only aliases, U-mode reads gated by mcounteren.CY/IR. |
| Machine HPM B03..B1F/B83..B9F, selectors 323..33F | Mapped zero, permitted writes ignored; no payload storage. |
| HPM aliases C03..C1F/C83..C9F | Read-only zero, M-mode only because user enables are zero. |
| IDs F11/F12/F13/F15 | Read-only zero, no payload storage. |
| `mhartid` F14 | Read-only parent identity input, no storage. The native core supplies its constant `HART_ID` parameter. |

Unlisted addresses, including `time[h]`, supervisor CSRs, delegation CSRs, and
unimplemented debug CSRs, raise illegal instruction. Normal address privilege and read-only
checks apply to every mapped CSR, including constants. PMP write restrictions
are not access exceptions. Initialize each required PMP address bound before
enabling an entry; reads of uninitialized address payloads have no guaranteed
value. Minimal `mcause` packing and PMP permission legalization are implementation
choices under the selected WLRL/WARL contracts.

Yosys development checks confirm the following retained state-bit budget:

```text
265 + ISA_C + 5*ISA_UMODE + 8*ISA_ZFINX + 608*ISA_PMP
    + DEBUG*(67 + ISA_C + 2*ISA_UMODE)
```

The default RV32I M+U configuration retains 270 bits. M-only without optional
state retains 265; U+C+Zfinx+PMP retains 887. All are resettable except the
512 PMP address payload bits when enabled. There are no inferred CSR memories,
unused HPM payloads, duplicate aliases, or constant-field flops. These are state
counts, not technology-mapped area or timing estimates.

## Optional debug state/events

With `DEBUG=1`, addresses 7B0/7B1/7B2 implement DCSR/DPC/dscratch0. They are
accessible only in Debug Mode; machine privilege alone is insufficient.
dscratch1 and all trigger CSRs remain unmapped. The external DM must use a
one-scratch-register debug ROM profile and advertise the matching hartinfo.

`debug_mode_i` is parent-owned. `debug_enter_i` is an accepted entry pulse,
with `debug_pc_i[31:0]` and `debug_cause_i[2:0]`; it captures DPC, cause, and
current privilege even during owning flush. The parent must arbitrate older
faults first. `dcsr_o`/`dpc_o` expose state for serialized resume and step control.
`dret_i` clears MPRV when resuming to U. `debug_ebreak_i` suppresses implicit
counter increments on the EBREAK entry edge. Counters also freeze throughout
Debug Mode while explicit legal counter writes still work. Debug Mode ignores
machine trap-entry events and allows machine CSR access independently of the
saved application privilege. WB prevents faulting debug instructions from
retiring or updating ordinary state.

DCSR stores ebreakm, step, cause, and (with U) ebreaku and one privilege bit.
Debugver=4, stopcount=1, mprven=1; stepie/stoptime and other unsupported fields
are zero. Unsupported prv encodings map to M. Debug entry updates only cause,
prv and DPC; debugger-written step/break controls persist. DPC has the same
alignment as mepc. All debug storage resets synchronously; disabled debug adds
no storage and drives zero state outputs. The [WB guide](../wb/README.md)
documents instruction/event bindings and verification.

## Component verification

```sh
make test COMPONENT=csregfile CONFIG=rv32i
make lint COMPONENT=csregfile CONFIG=rv32i
```

Use a complete hardware YAML configuration to exercise optional state; enabled
Zfinx here tests CSR storage without claiming an implemented FPU. Tests use the
project cocotb/pyuvm stack and an independent model of architectural words:

- `directed`: every 12-bit CSR address in M/U, all six CSR forms plus invalid
  operations, suppression based on source/destination encodings, field masks,
  WARL behavior, mapped zeros, aliases, IRQ levels, stalls/commit/flush/reset.
- `counters`: rollover, low/high writes, explicit-write priority, counting during
  stalls, independent CY/IR inhibition and old-inhibit edge semantics.
- `events`: baseline synchronous/interrupt causes, trap/MRET state and priority,
  return to U/M, FP aliasing/accrual, explicit-write priority, and independent events.
- `pmp`: all config words/address entries, reserved permission legalization,
  per-entry locking, locked TOR predecessor protection, reset unlock/address
  retention, disabled zero mapping, privilege and out-of-range access faults.
- `randomized`: 4,096 interleaved access/control/event cycles followed by state
  reads, reproducible with `SEED`.

Development regressions cover all sixteen combinations of U, C, Zfinx CSR state,
PMP state (and representative I/E/M settings). Representative Yosys checks inspect
state widths, reset coverage, absence of memories/latches, and full synthesis.
The [core](../core/README.md) connects serialization, trap arbitration, retirement
and shared-PMP state; its RVFI/CSR and software tests add integrated observations.
Core debug/external-DM integration and functional floating-point execution
remain open.

Reference semantics: [Zicsr 2.0](https://docs.riscv.org/reference/isa/v20260120/unpriv/zicsr.html),
[machine-level privileged ISA](https://docs.riscv.org/reference/isa/v20260120/priv/machine.html),
[Debug 1.0 Sdext](https://docs.riscv.org/reference/debug/v1.0/Sdext.html),
and [Zfinx 1.0](https://docs.riscv.org/reference/isa/v20260120/unpriv/zfinx.html).
