# Native processor core

[`uqu_core.v`](../../../src/uquintus/uqu_core.v) connects the actual IF, DE, EX,
MEM and WB stages. It owns all four pipeline boundaries, the GPR file,
`uqu_hazard`, one shared two-port `uqu_pmp`, `uqu_pipeline_ctrl`, current
privilege and architectural resume-PC tracking. WB owns the CSR file and MEM
owns the LSU. Instruction and data memories remain external.

The native core supports RV32I+Zicsr, configurable M/U privilege, and the
implemented E, M, C, PMP and Zifencei options. Forwarding paths, DE operand
retention, FF/latch GPR storage, compressed strategy/placement, iterative
arithmetic configuration, frontend depth and the two existing branch policies
are passed to their owning components. The source list is Bender target `rtl`.

Zfinx/FPU, XIF issue-ID/cleanup integration and core debug sequencing remain
unfinished. `ISA_ZFINX=1`, `ISA_F=1`, `ISA_A=1`, `XIF=1`, `DEBUG=1`, or
`MUA_HARDENED=1` deliberately fail RTL elaboration. This guard keeps a selected
feature from silently acting as disabled. Existing standalone XIF/debug stage
tests and interfaces remain available for later integration.

## External connections

| Ports | Contract |
| --- | --- |
| `clk_i`, `rst_ni` | One clock; synchronous active-low reset. Reset clears control/validity, not GPR or pipeline payload storage. |
| `boot_addr_i[31:0]` | Word-aligned boot entry; hold stable through reset. |
| `hart_id_i[31:0]` | Stable integration identity, read through `mhartid`. |
| `irq_software_i`, `irq_timer_i`, `irq_external_i` | Synchronous level inputs reflected directly in `mip`. Peripheral/integration logic clears their sources. |
| `imem_req_o`, `imem_addr_o[31:0]` | Read-only word-aligned native OBI request; grant via `imem_gnt_i`. |
| `imem_rvalid_i`, `imem_rdata_i[31:0]`, `imem_err_i` | Instruction response; an error causes a precise instruction access fault. |
| `dmem_req_o`, `dmem_we_o`, `dmem_addr_o[31:0]`, `dmem_wdata_o[31:0]`, `dmem_be_o[3:0]` | Read/write word-aligned native OBI request; grant via `dmem_gnt_i`; subword lanes selected by byte enables. |
| `dmem_rvalid_i`, `dmem_rdata_i[31:0]`, `dmem_err_i` | Load/store completion, including error completion for stores. |
| `fence_req_o`, `fence_ack_i` | Base FENCE external ordering handshake. Tie acknowledgement high if no external ordering work is required. |
| `fencei_req_o`, `fencei_ack_i` | External instruction synchronization when Zifencei is enabled; otherwise request is inactive. |
| `xif_*` | Standard issue/register/commit/result declarations retained with XIF disabled. All core-driven outputs are inactive and inputs are ignored. |

Both memory ports allow independent variable latency, with one outstanding
transaction each. Once presented, a request persists until grant, including
through a redirect that kills its owning instruction. Responses have no
backpressure and arrive at least one cycle after their grant. There are no
internal timeouts. Reset also clears transaction tracking: the memory system
must discard pre-reset responses before reset release. See the
[interface specification](../../../doc/uqu_spec.interfaces.md) for the complete
memory and reset contracts.

## Pipeline integration

`u_ctrl` emits readiness, accepted transfers, flushes, boundary enables and
replacement validity. Validity changes only when the corresponding enable is
asserted. Payload captures only for an enabled valid replacement. Every token
retains its original PC, instruction bits, length and privilege through WB.
These internal signals are available to verification; the core adds no trace
output pins.

DE branches redirect only on accepted transfer. EX operands select the resolved
register, PC, immediate or zero as decoded. Store data is resolved in EX.
An operand admitted under a next-cycle bypass guarantee is captured once it
becomes ready if EX is held; it cannot disappear when its producer drains.
No LSU effective address or uncommitted CSR placeholder is forwarded as a
register result. A load becomes forwardable only from the registered successful
MEM response. CSR results become available at successful WB commit.

WB faults and MRET redirect through the controller. WB is not flushed by its
own accepted event; its boundary is cleared by accepted transfer. Younger
memory requests require the older WB token's non-faulting proof. IRQ entry
drains EX/MEM/WB, saves the pending DE PC or architectural resume PC, and uses
direct/vectored `mtvec` dispatch. Current privilege changes on WB trap/MRET or
IRQ entry. IF uses current privilege; MEM applies MPRV/MPP to the token's
privilege before querying the shared PMP checker.

## Running programs

```sh
make test COMPONENT=core CONFIG=rv32i
make test COMPONENT=core CONFIG=rv32im SEED=42
make test COMPONENT=core CONFIG=rv32ic
make test COMPONENT=core CONFIG=rv32ic_decompress_de
make test COMPONENT=core CONFIG=rv32ic_decoder_c
make test COMPONENT=core CONFIG=rv32i_pmp
make test COMPONENT=core CONFIG=rv32i_retained
make test COMPONENT=core CONFIG=rv32i_zifencei
make lint COMPONENT=core CONFIG=rv32i
```

The common runner uses [`config/sim/core.yml`](../../../config/sim/core.yml).
Select one program suite with `TEST=<name>`; use `WAVES=1` for waveforms.
Custom complete hardware YAML files use the same `CONFIG=<path>` argument.

`core_env.py` supplies separate instruction/data agents with randomized grants
and response delays. It checks persistent requests, word alignment, outstanding
limits, byte lanes, error completions and reset cancellation. Programs are
encoded locally without a cross-compiler dependency. A separate instruction
interpreter checks original instruction identity, retirement order, branch/link
PCs, register writes, committed memory, CSR state and precise trap PC/cause/value.
Registers must be initialized by software before the interpreter reads them.

| Suite | Checks |
| --- | --- |
| `integer` | Seeded RV32I register/immediate arithmetic, shifts and comparisons; x0; dependent/overwritten destinations; branches, loops, JAL/JALR and skipped poison stores. |
| `memory` | Signed/unsigned byte/halfword/word loads, byte-lane stores, load consumers, store-data dependencies, branch operands, FENCE and configured FENCE.I. |
| `traps` | Misaligned data/branch targets, illegal instruction/CSR, disabled M and RV32E register restrictions, ECALL, EBREAK with zero `mtval`, and explicit load/store error responses. |
| `precise` | A WB CSR fault prevents a younger store from issuing before recovery; instruction bus errors preserve fault PC/value and resume through MRET. |
| `pmp` | Disabled CSR reads/writes, or enabled TOR permissions and MPRV/MPP-denied loads/stores without external requests. |
| `privilege` | MRET into U, privileged CSR rejection, trap/MRET recovery; enabled PMP permits U code. M-only configurations retain MPP=M. |
| `interrupts` | External interrupt while a load is pending, pipeline drain, vectored entry, saved resume PC, handler CSR reads and MRET restart. |
| `extensions` | Configured M operations including zero divisor/signed overflow; configured compressed instructions, cross-word assembly and original instruction identity. |
| `reset` | Restart at a new boot address during an accepted, incomplete data transaction; no stale retirement/store after reset. |

This interpreter is an initial integration oracle, **not the required Spike
adapter or RVFI/riscv-formal verification**. Those checks, full architectural
coverage, CI and ASIC implementation remain follow-ups; passing these programs
does not complete the first milestone's acceptance criteria.
