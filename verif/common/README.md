# Native RVFI observation

`uqu_rvfi.sv` is a passive collector shared with future formal integration.
It has ordinary signal inputs, no hierarchy references, file I/O, timing delays
or assertions that constrain the processor. `uqu_core_tb.sv` in
[`verif/sim/core/`](../sim/core/README.md) connects these inputs to real core
transfers and operands. Hierarchical connections are confined to that simulation
wrapper. The simulation-only `uqu_rvfi_trace.sv` writes the resulting JSONL.

The profile follows the [RISC-V Formal RVFI contract](https://yosyshq.readthedocs.io/projects/riscv-formal/en/latest/rvfi.html),
checked 2026-10-21. The formal-tool revision, environment and proof configuration
are not yet pinned; this collector is not a completed riscv-formal harness.
Formal core binding and proof execution are deferred until a working open-source
formal toolchain is selected and configured. `riscv-formal` remains the planned
framework; no complete toolchain has yet been validated for this core.

| Item | Native observation profile |
| --- | --- |
| Dimensions | `NRET=1`, `XLEN=32`, `ILEN=32`; 64-bit order counter. |
| Events | One valid record for successful WB retirement or an accepted synchronous instruction trap. Stalls, bubbles, killed instructions and IRQ entry itself produce no instruction record. |
| Instruction | Original bits; compressed instructions are zero-extended, never replaced with their expanded encoding. Instruction-access faults report zero instruction bits. |
| Sources | Actual operands consumed in DE for branches/CSR, or EX for arithmetic/LSU; addresses and values travel with accepted transfers through verification-only storage. Unused sources and x0 report zero. |
| Destination | Actual committed GPR write; x0, nonwriters and traps report zero address/data. |
| PCs | Original PC and actual successor, including accepted MRET and synchronous trap redirects. |
| Privilege | Token privilege: M=3, U=0. `rvfi_ixl=1`; `rvfi_halt=0`. |
| Handler entry | `rvfi_intr` marks the first instruction following an asynchronous entry or synchronous trap. Pending entry survives bubbles and stalls. |
| Memory | `RISCV_FORMAL_ALIGNED_MEM` convention: word-aligned address, lane-shifted masks/data. Read data comes from the raw accepted response, independently of load extension/writeback. Only mask-selected bytes are meaningful. |
| Faults | `RISCV_FORMAL_MEM_FAULT` fields are present. Instruction access faults set the fault flag without a data mask; load/store access faults report attempted lanes through the corresponding fault mask. Traps report no committed memory masks or GPR write. Misalignment uses the ordinary trap flag. |
| Reset | Control/order reset synchronously; order restarts at zero. No valid record is emitted during reset. Observation payload is qualified by core validity. |

The memory conventions above must be selected in any future riscv-formal
configuration. Access-fault reporting includes internal PMP denials. Trap cause
and value, and asynchronous entry PC/cause/target, are diagnostic fields in the
simulation file; they are not new standard RVFI signals or core output ports.

Per-CSR state is observed by `uqu_rvfi_csrs.sv`. The canonical unguarded
`uqu_rvfi_csr_list.vh` supplies 102 channel names, widths, slots and address
aliases; `uqu_rvfi_csrs.vh` supplies the declaration/connection helpers. Python
verification reads this same catalog through `verif/sim/common/rvfi_csrs.py`.
The native channels cover machine identity/setup/trap CSRs, optional U-mode
configuration, all sixteen PMP entries, counters and constant-zero HPM CSRs.
Optional Zfinx adds `fflags`, `frm` and `fcsr` views of actual committed state.
Debug-only state remains excluded while core debug is unsupported.

Each channel exposes `rvfi_csr_<name>_{rmask,wmask,rdata,wdata}`. Masks qualify
meaningful bits; inactive channels are zero-masked. Explicit CSR access uses
the CSR unit's actual successful read/write qualification. CSRRW with `rd=x0`
has no read mask; zero-source CSRRS/CSRRC have no explicit write mask. Legal
writes to hardwired or locked state report its unchanged committed value.
An illegal CSR access has no explicit CSR masks, but its trap still reports
implicit machine-state updates.

The wrapper registers the base RVFI record and CSR pre-state at acceptance.
Post-state is read from the actual CSR state during the following observation
cycle, avoiding a second implementation of WARL, locks or trap updates. All
instruction and CSR fields describe the same accepted event. The SV writer
samples the resulting record on the falling edge; this changes observation
timing only. Processor RTL and execution timing are unchanged.

`mcycle`, `minstret` and `mhpmcounter3` through `mhpmcounter31` are 64-bit
channels. Their machine/user low/high addresses share a canonical machine
channel, with half-width masks. Autonomous increments are between instruction
observations: a read-only counter event has equal read/write data and no write
mask. Explicit counter writes report the actual updated half, preserving the
other half. This follows the [RVFI CSR semantics](https://yosyshq.readthedocs.io/projects/riscv-formal/en/latest/csrs.html).
Future formal configurations must select the corresponding
`RISCV_FORMAL_CSR_<NAME>` defines for channels their checkers consume. Exposing
HPM/PMP channels here does not imply formal-tool models or proofs cover them.

Synchronous traps implicitly read `mstatus`/`mtvec` and write
`mstatus`/`mepc`/`mcause`/`mtval`; MRET reads `mstatus`/`mepc` and writes
`mstatus`. IRQ entry has these same trap channels in its separate JSON event,
without asserting RVFI instruction validity or consuming an instruction order.
Feature-disabled illegal accesses remain zero-masked. Disabled PMP CSRs stay
legal and report their hardwired zero state. Unreset PMP address payload is not
assumed to have a defined reset value.

For native-core XIF simulation, the wrapper captures actual issue operands by
ID. Standard RVFI contains the first two used sources and primary destination;
`verif/sim/core/uqu_xif_trace.sv` additionally records all three operands and both
actual GPR write ports in `xif.jsonl`, correlated with the same epoch/order.
This companion diagnostic is not a standard RVFI multi-destination extension and
does not imply formal custom-instruction proofs. The custom retirement oracle
checks the extra effects, including atomic paired update and ignored x0/x1.

FP flag accrual reads and writes the low five bits of `fflags` and `fcsr`; dynamic
rounding observes the `frm` field. Explicit alias writes also mark affected
fields in the other views. These observations use actual WB CSR state and are
checked against an independent retirement oracle; disabled FP views are masked.
Standard RVFI contains the first two FP source operands. Three-source FMA is
checked by the core retirement oracle; no nonstandard source port is added.

RVFI_BUS, formal FPU instruction modeling, standard formal modeling of custom/paired
results, debug, rollback, alternative arithmetic, formal core
signal binding, environment assumptions and actual instruction proofs remain
follow-ups. Yosys parsing/structural checks of the collector establish tool
compatibility only, not proof of architectural correctness.
