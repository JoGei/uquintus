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

CSR instructions are visible through instruction/source/destination records,
but per-CSR `rvfi_csr_*` state channels are not implemented. CSR state and trap
diagnostics still have separate simulation checks. RVFI_BUS, FPU/custom/paired
results, debug, rollback, alternative arithmetic, Spike comparison, formal core
signal binding, environment assumptions and actual instruction proofs remain
follow-ups. Yosys parsing/structural checks of the collector establish tool
compatibility only, not proof of architectural correctness.
