# Native processor core

[`uqu_core.v`](../../../src/uquintus/uqu_core.v) connects the actual IF, DE, EX,
MEM and WB stages. It owns all four pipeline boundaries, the GPR file,
`uqu_hazard`, one shared two-port `uqu_pmp`, `uqu_pipeline_ctrl`, current
privilege and architectural resume-PC tracking. WB owns the CSR file and MEM
owns the LSU. Instruction and data memories remain external.

The native core supports RV32I+Zicsr, configurable M/U privilege, and the
implemented E, M, C, PMP and Zifencei options. Forwarding paths, DE operand
retention, FF/latch GPR storage, compressed strategy/placement, iterative
arithmetic configuration, frontend depth and none/static-not-taken/bimodal branch policies
are passed to their owning components. The source list is Bender target `rtl`.

The [core-owned XIF controller](../xif_ctrl/README.md) connects issue/ID/cleanup
to the existing DE and WB endpoints, with up to four live offloads, three-bit
IDs and in-order result/retirement handling. `config/rv32i_xif.yml` enables the
initial uncompressed standard-channel profile. Shared LSU, execution traps and
the standard compressed offload channel remain deferred.

Native Zfinx executes through CVFPU with the `rv32i_zfinx` preset. The
[FPU tests](../fpu/README.md) cover arithmetic, lifecycle and core retirement;
RVFI includes `fflags`, `frm` and `fcsr` state. Core debug sequencing remains
unfinished. `ISA_F=1`, `ISA_A=1`, `DEBUG=1`, or
`MUA_HARDENED=1` deliberately fail RTL elaboration. This guard keeps a selected
feature from silently acting as disabled. Standalone debug stage tests and
interfaces remain available for later integration.

## External connections

Hart identity is the compile-time `parameter [31:0] HART_ID = 32'd0`, explicitly
set in hardware YAML and forwarded to the core instantiation. There is no native
hart-ID input. `mhartid` and outgoing/checked CV-X-IF hart IDs use this constant.
Standalone DE/WB/CSR components retain parent-supplied identity inputs; the core
ties those inputs to `HART_ID` so synthesis can fold the constant.

| Ports | Contract |
| --- | --- |
| `clk_i`, `rst_ni` | One clock; synchronous active-low reset. Reset clears control/validity, not GPR or pipeline payload storage. |
| `boot_addr_i[31:0]` | Word-aligned boot entry; hold stable through reset. |
| `irq_software_i`, `irq_timer_i`, `irq_external_i` | Synchronous level inputs reflected directly in `mip`. Peripheral/integration logic clears their sources. |
| `imem_req_o`, `imem_addr_o[31:0]` | Read-only word-aligned native OBI request; grant via `imem_gnt_i`. |
| `imem_rvalid_i`, `imem_rdata_i[31:0]`, `imem_err_i` | Instruction response; an error causes a precise instruction access fault. |
| `dmem_req_o`, `dmem_we_o`, `dmem_addr_o[31:0]`, `dmem_wdata_o[31:0]`, `dmem_be_o[3:0]` | Read/write word-aligned native OBI request; grant via `dmem_gnt_i`; subword lanes selected by byte enables. |
| `dmem_rvalid_i`, `dmem_rdata_i[31:0]`, `dmem_err_i` | Load/store completion, including error completion for stores. |
| `fence_req_o`, `fence_ack_i` | Base FENCE external ordering handshake. Tie acknowledgement high if no external ordering work is required. |
| `fencei_req_o`, `fencei_ack_i` | External instruction synchronization when Zifencei is enabled; otherwise request is inactive. |
| `xif_*` | Standard coupled issue/register and commit/result channels. When disabled, all outputs are inactive and inputs ignored. When enabled, DE instruction bits are visible for parallel recognition before issue qualification. |

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
output pins. The simulation top is now `uqu_core_tb`, which instantiates the
core and the [passive RVFI collector](../../common/README.md).

DE corrections redirect only on accepted transfer; BTB-backed predictions travel
through the parent-owned IF/DE payload, and correct predictions do not flush
the frontend. The [predictor guide](../bpu/README.md) describes
training and recovery. EX operands select the resolved
register, PC, immediate or zero as decoded. Store data is resolved in EX.
An operand admitted under a next-cycle bypass guarantee is captured once it
becomes ready if EX is held; it cannot disappear when its producer drains.
No LSU effective address or uncommitted CSR placeholder is forwarded as a
register result. MEM issues a load/store and advances on grant; WB owns its response and
completion. A raw load response can write the GPR file at retirement, but
becomes available to dependent operands only after registration: through a
buffered WB response or the updated GPR file. CSR results become available at successful WB commit.

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
make test COMPONENT=core CONFIG=rv32i_xif TEST=xif
make lint COMPONENT=core CONFIG=rv32i
```

The common runner uses [`config/sim/core.yml`](../../../config/sim/core.yml)
and Bender target `core_test`, selecting the native RTL plus the SV wrapper,
RVFI collector and JSONL writer. Bender target `rtl` continues to select only
processor Verilog sources.
Select one program suite with `TEST=<name>`; use `WAVES=1` for waveforms.
Custom complete hardware YAML files use the same `CONFIG=<path>` argument.
The separate [ELF execution target](../core_elf/README.md) reuses this environment
with shared instruction/data RAM and compiler-built programs. It is selected
with `COMPONENT=core_elf ELF=<path>`; the directed suites here retain their
separate instruction/data images and require no RISC-V compiler.

`core_env.py` supplies separate instruction/data agents with randomized grants
and response delays. It checks persistent requests, word alignment, outstanding
limits, byte lanes, error completions and reset cancellation. Programs are
encoded locally without a cross-compiler dependency. A separate instruction
interpreter checks original instruction identity, retirement order, branch/link
PCs, register writes, committed memory, CSR state and precise trap PC/cause/value.
Registers must be initialized by software before the interpreter reads them.

| Suite | Checks |
| --- | --- |
| `csrs` | Six CSR instruction forms, suppressed reads/writes, WARL/read-only behavior, 64-bit counter halves and aliases, inhibition/increments, PMP locking, constant HPM/identity state and illegal-write traps. |
| `hart_id` | Configured 32-bit `mhartid` reads, read-only write rejection, value preserved after trapping, and absence of the removed top-level port. |
| `integer` | Seeded RV32I register/immediate arithmetic, shifts and comparisons; x0; dependent/overwritten destinations; branches, loops, JAL/JALR and skipped poison stores. |
| `prediction` | Bimodal loop learning and exit recovery, changing JALR targets, compressed branch loops, skipped wrong-path instructions and cold lookup after configured FENCE.I. Baseline modes run the same architectural program. |
| `memory` | Signed/unsigned byte/halfword/word loads, byte-lane stores, load consumers, store-data dependencies, branch operands, FENCE and configured FENCE.I. |
| `traps` | Misaligned data/branch targets, illegal instruction/CSR, disabled M and RV32E register restrictions, ECALL, EBREAK with zero `mtval`, and explicit load/store error responses. |
| `precise` | A WB CSR fault prevents a younger store from issuing before recovery; instruction bus errors preserve fault PC/value and resume through MRET. |
| `pmp` | Disabled CSR reads/writes, or enabled TOR permissions and MPRV/MPP-denied loads/stores without external requests. |
| `privilege` | MRET into U, privileged CSR rejection, trap/MRET recovery; enabled PMP permits U code. M-only configurations retain MPP=M. |
| `interrupts` | External interrupt while a load is pending, pipeline drain, vectored entry, saved resume PC, handler CSR reads and MRET restart. |
| `extensions` | Configured M operations including zero divisor/signed overflow; configured compressed instructions, cross-word assembly and original instruction identity. |
| `reset` | Restart at a new boot address during an accepted, incomplete data transaction; no stale retirement/store after reset. |
| `xif` | Enabled: four live offloads, standard commit/result timing, dependencies/ternary operands, paired results, malformed-result containment, rejection, late memory faults, IRQ cleanup/reissue and RV32E defenses. Disabled: inputs ignored and outputs inactive. |

The interpreter now consumes RVFI retirement records and independently checks
their consumed operands, mode, next PC, memory lanes, fault masks and handler
markers. It retains internal controller observations for timing and precise
fault diagnostics. Every suite also checks the saved SV trace against its
sampled records.

XIF source observations are captured at the actual coupled issue/register
handshake and retained by ID until DE advances; they are not re-read from GPRs
after acceptance. Standard RVFI reports the first two used operands and primary
destination. The companion `xif.jsonl` reports all three used operand values and
both actual write ports, correlated by RVFI epoch/order, with one record per
custom retirement. `xif-agent.json` records protocol activity and maximum live
offloads. The independent custom-instruction oracle uses architectural GPR
state, while the coprocessor computes from the actual delivered operands. Spike
checking continues to reject XIF configurations until a custom reference contract
is selected; no custom comparison is silently skipped.

Each run writes `rvfi.jsonl` beside `results.xml` and `run.json`. Records use
unsigned JSON integers and one of three types:

- `reset`: consecutive `epoch`, starting at zero.
- `instruction`: epoch, `rvfi_*` fields (valid is implied), and diagnostic
  `cause`/`tval` fields, zero for successful retirement, plus `csrs`.
- `interrupt`: epoch, saved `pc`, `cause`, and handler `target`; no instruction
  order is consumed. The next instruction carries `rvfi_intr=1`.

Instruction and interrupt records include a sparse `csrs` object. Each active
channel is keyed by its canonical name (for example `mstatus` or `mcycle`) and
contains unsigned `rmask`, `wmask`, `rdata` and `wdata`. Inactive channels are
omitted. The same masks/data are exposed as flat standard RVFI CSR signals on
the verification top. `rvfi_csrs.py` checks every channel against the shared
independent CSR model, including implicit trap/MRET effects and IRQ entry.

Order counts accepted instruction events, including synchronous traps, and
restarts at zero in each reset epoch. The wrapper registers each accepted event
so CSR pre-state can be paired with real committed post-state. The SV writer
records it at the falling edge of that observation cycle.
`verif/sim/common/rvfi_trace.py` reads and validates the
file without a simulator. A direct simulator invocation can override the path
with `+rvfi_trace_file=<path>`; the Make flow uses its isolated run directory.

This interpreter is an initial integration oracle, **not the required Spike
adapter or completed riscv-formal verification**. Formal core binding/proofs,
Spike comparison, full architectural coverage,
CI and ASIC implementation remain follow-ups; passing these programs does
not complete the first milestone's acceptance criteria.
Formal core binding and proof execution are deferred until selection and
configuration of an open-source formal toolchain. The implemented CSR channels
extend the simulation coverage without selecting a formal toolchain.
